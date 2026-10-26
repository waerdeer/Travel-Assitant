import json
import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional
from time import monotonic

import httpx

from app.core.exceptions import ToolCallError

logger = logging.getLogger("app.mcp.client")

# 这些错误是服务端/网络临时抽风，换参数或稍后重试有意义。
_RETRYABLE_MARKERS = (
    "timeout",
    "timed out",
    "temporarily",
    "rate limit",
    "too many requests",
    "try again",
    "502",
    "503",
    "504",
)


@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""


@dataclass
class MCPToolResult:
    """一次 MCP 工具调用的结果。

    error_code / retryable 是给**上层和 LLM** 用的，不是给人看的：
      - error_code  机器可判定，让测试能断言 code == "tool_not_found" 而不是匹配中文
      - retryable   决定 LLM 该不该重试。必须是类型化的布尔值，不能靠
                    "timeout" in error 这类子串嗅探 —— 服务端换个措辞就会静默失效，
                    那正是本次事故的同一类错误。
    """

    success: bool
    content: Any = None
    error: Optional[str] = None
    is_error: bool = False
    error_code: Optional[str] = None
    retryable: bool = False


def _classify_rpc_error(code: Optional[int], message: str) -> tuple[str, bool]:
    """JSON-RPC 错误码 → (error_code, retryable)。

    核心原则：内容类失败（参数错、没搜到）可重试；
             协议类失败（工具不存在、非 JSON-RPC 响应）重试一万次结果一样。
    """
    msg = (message or "").lower()

    if code == -32601 or "tool not found" in msg or "未知工具" in msg:
        return "tool_not_found", False
    if code == -32602:
        return "invalid_params", False
    if code in (-32603, -32000, -32001):
        # 服务端内部错误，值得再试一次
        return "server_error", True
    if any(marker in msg for marker in _RETRYABLE_MARKERS):
        return "server_error", True
    return "rpc_error", False


class MCPClient:
    """统一管理多个外部 MCP Server 的连接与工具调用。

    支持两种传输模式:
      - http: 直接通过 HTTP 调用远程 MCP Server（推荐，无需本地依赖）
      - stdio: 启动本地子进程（需要 Node.js / Python 等运行时）

    用法:
        client = MCPClient()
        await client.load_config("app/mcp/servers.json")
        result = await client.call_tool("amap", "maps_text_search", {
            "keywords": "景点", "city": "北京"
        })
        await client.close()

    注意工具名：高德服务端暴露的名字是 maps_* 前缀，没有 amap_ 前缀。
    """

    def __init__(self):
        self._sessions: dict[str, Any] = {}
        self._servers: dict[str, MCPServerConfig] = {}
        self._http_client: Optional[httpx.AsyncClient] = None
        self._rate_lock = asyncio.Lock()
        self._next_call_at = 0.0

    def _resolve_env(self, raw: dict[str, str]) -> dict[str, str]:
        resolved = {}
        for key, value in raw.items():
            if value.startswith("${") and value.endswith("}"):
                resolved[key] = self._lookup_env(value[2:-1])
            else:
                resolved[key] = value
        return resolved

    def _resolve_url(self, url: str) -> str:
        if "${" in url:
            for match in set(__import__("re").findall(r"\$\{(\w+)\}", url)):
                url = url.replace(f"${{{match}}}", self._lookup_env(match))
        return url

    def _lookup_env(self, name: str) -> str:
        """优先取进程环境变量；缺失时回落到 pydantic settings（.env 文件）。

        MCP URL/参数里的 ${XXX} 是从 os.environ 解析的，而 .env 只被
        pydantic-settings 读进 settings，不会自动注入 os.environ，
        因此这里必须兜底，否则高德 key 等会解析为空。
        """
        value = os.environ.get(name)
        if value:
            return value
        try:
            from app.core.config import settings
            return getattr(settings, name.lower(), "")
        except Exception:
            return ""

    async def load_config(self, config_path: str) -> None:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for name, cfg in raw.items():
            if not cfg.get("enabled", True):
                continue
            self._servers[name] = MCPServerConfig(
                name=name,
                transport=cfg.get("transport", "stdio"),
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
                url=cfg.get("url", ""),
            )

    async def connect(self, server_name: str) -> None:
        if server_name in self._sessions:
            return
        cfg = self._servers.get(server_name)
        if cfg is None:
            raise ToolCallError(f"未配置 MCP Server: {server_name}")

        if cfg.transport == "http":
            await self._connect_http(server_name, cfg)
        else:
            await self._connect_stdio(server_name, cfg)

    async def _connect_http(self, server_name: str, cfg: MCPServerConfig) -> None:
        url = self._resolve_url(cfg.url)
        self._sessions[server_name] = {"type": "http", "url": url}

    async def _connect_stdio(self, server_name: str, cfg: MCPServerConfig) -> None:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as e:
            raise ToolCallError(
                "stdio 模式需要 mcp SDK，请先安装 Python 3.10+ 并执行: pip install mcp"
            ) from e

        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=self._resolve_env(cfg.env),
        )
        async with stdio_client(params) as (read, write):
            session = ClientSession(read, write)
            await session.initialize()
            self._sessions[server_name] = {"type": "stdio", "session": session}

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            # 超时与 app/graph/nodes.py 的 REACT_RECURSION_LIMIT 是一对：
            # limit 提到 12 后单次请求最坏会叠加多次工具调用，60s 的超时
            # 会让最坏延迟失控，20s(连接 5s) 对实测约 1s 的高德接口足够宽松。
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=5.0)
            )
        return self._http_client

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> MCPToolResult:
        session_info = await self._get_session(server_name)
        from app.core.config import settings
        async with self._rate_lock:
            await asyncio.sleep(max(0, self._next_call_at - monotonic()))
            self._next_call_at = monotonic() + settings.mcp_min_interval_seconds

        if session_info["type"] == "http":
            return await self._call_tool_http(session_info["url"], tool_name, arguments)
        else:
            return await self._call_tool_stdio(session_info["session"], tool_name, arguments)

    def _http_headers(self) -> dict:
        return {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _flatten_text(content: Any) -> str:
        """把 content 里的文本拼出来，兼容 TextContent 对象和 dict 两种表示。"""
        if not isinstance(content, list):
            return str(content or "")
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
            if text:
                parts.append(str(text))
        return "\n".join(parts)

    async def _call_tool_http(self, url: str, tool_name: str, arguments: dict) -> MCPToolResult:
        """通过 HTTP 调用 MCP 工具。

        分四段判定，任何一段不通过都返回 success=False。
        旧实现只有「try/except 网络异常」一段，于是 JSON-RPC 层的 error 被
        data.get("result", {}) 静默降级成 {}，再以 success=True 返回 ——
        服务端明确报错，客户端却报成功，错误从此消失。
        """
        client = self._get_http_client()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        # --- 第 1 段：传输层 ---
        try:
            resp = await client.post(url, json=payload, headers=self._http_headers())
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else 0
            body = e.response.text[:400] if e.response is not None else ""
            logger.warning(
                "MCP HTTP 错误 tool=%s status=%s body=%s", tool_name, status, body
            )
            return MCPToolResult(
                success=False,
                error=f"HTTP {status}: {body}",
                error_code="http_error",
                retryable=status >= 500 or status in (408, 429),
            )
        except Exception as e:  # 超时 / 连接失败 / DNS
            logger.warning(
                "MCP 传输失败 tool=%s: %s: %s", tool_name, type(e).__name__, e
            )
            return MCPToolResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
                error_code="transport_error",
                retryable=True,
            )

        # --- 第 2 段：响应体解析 ---
        if not resp.text.strip():
            logger.warning("MCP 返回空响应体 tool=%s", tool_name)
            return MCPToolResult(
                success=False,
                error="MCP 服务端返回空响应体",
                error_code="empty_response",
                retryable=True,
            )
        try:
            data = self._parse_sse_or_json(resp)
        except Exception as e:
            logger.error(
                "MCP 响应解析失败 tool=%s: %s; raw=%s", tool_name, e, resp.text[:300]
            )
            return MCPToolResult(
                success=False,
                error=f"响应解析失败: {e}; raw={resp.text[:300]}",
                error_code="protocol_error",
                retryable=False,
            )

        # --- 第 3 段：JSON-RPC 层的 error 键（本次事故的正解）---
        if isinstance(data.get("error"), dict):
            err = data["error"]
            code = err.get("code")
            message = str(err.get("message", ""))
            error_code, retryable = _classify_rpc_error(code, message)
            logger.error(
                "MCP tools/call 失败 tool=%s code=%s msg=%s", tool_name, code, message
            )
            return MCPToolResult(
                success=False,
                error=f"[{code}] {message}",
                error_code=error_code,
                retryable=retryable,
            )

        # --- 第 3.5 段：不是 JSON-RPC 信封（防御性）---
        # 期望的响应一定带 jsonrpc 与 result。缺了说明服务端返回了别的东西
        # （网关错误页、额度用尽的业务错误体等），不能当成正常结果。
        if not data.get("jsonrpc"):
            raw = json.dumps(data, ensure_ascii=False)[:300]
            logger.error("MCP 返回非 JSON-RPC 响应 tool=%s body=%s", tool_name, raw)
            return MCPToolResult(
                success=False,
                error=f"非 JSON-RPC 响应: {raw}",
                error_code="protocol_error",
                retryable=False,
            )

        # --- 第 4 段：正常响应 / isError 标志 ---
        result = data.get("result")
        if not isinstance(result, dict):
            raw = json.dumps(data, ensure_ascii=False)[:300]
            logger.error("MCP 响应缺少 result tool=%s body=%s", tool_name, raw)
            return MCPToolResult(
                success=False,
                error=f"响应缺少 result: {raw}",
                error_code="protocol_error",
                retryable=False,
            )

        content = result.get("content", [])
        if bool(result.get("isError", False)):
            message = self._flatten_text(content) or "工具返回 isError=true"
            rate_limited = any(marker in message.upper() for marker in ("QPS_HAS_EXCEEDED", "TOO_MANY_REQUESTS", "ACCESS_TOO_FREQUENT"))
            logger.error("MCP 工具业务失败 tool=%s msg=%s", tool_name, message[:300])
            return MCPToolResult(
                success=False,
                content=content,
                is_error=True,
                error=message,
                error_code="rate_limited" if rate_limited else "tool_error",
                retryable=rate_limited,
            )

        return MCPToolResult(success=True, content=content, is_error=False)

    async def _call_tool_stdio(self, session, tool_name: str, arguments: dict) -> MCPToolResult:
        """stdio 传输：JSON-RPC 错误抛 McpError，业务失败走 result.isError。"""
        try:
            result = await session.call_tool(tool_name, arguments)
        except Exception as e:
            code = getattr(getattr(e, "error", None), "code", None)
            error_code, retryable = _classify_rpc_error(code, str(e))
            logger.error("stdio tools/call 异常 tool=%s code=%s err=%s", tool_name, code, e)
            return MCPToolResult(
                success=False, error=str(e), error_code=error_code, retryable=retryable
            )

        content = result.content if hasattr(result, "content") else result
        if bool(getattr(result, "isError", False)):
            message = self._flatten_text(content) or "工具返回 isError=true"
            logger.error("stdio 工具业务失败 tool=%s msg=%s", tool_name, message[:300])
            return MCPToolResult(
                success=False,
                content=content,
                is_error=True,
                error=message,
                error_code="tool_error",
                retryable=False,
            )
        return MCPToolResult(success=True, content=content, is_error=False)

    def _parse_sse_or_json(self, resp: httpx.Response) -> dict:
        """解析 MCP 响应：可能是 SSE 格式或纯 JSON。

        找不到 data 行时抛异常而不是 return {} —— 后者是另一个静默失败入口，
        会让「SSE 解析失败」伪装成「响应内容为空」。
        """
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            for line in resp.text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk:
                        return json.loads(chunk)
            raise ValueError(f"SSE 响应中没有 data 行: {resp.text[:200]}")
        return resp.json()

    async def list_tools(self, server_name: str) -> list[dict]:
        session_info = await self._get_session(server_name)

        if session_info["type"] == "http":
            client = self._get_http_client()
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }
            resp = await client.post(session_info["url"], json=payload, headers=self._http_headers())
            data = self._parse_sse_or_json(resp)
            # 与 call_tool 同样的道理：error 键必须抛出来，不能降级成空清单，
            # 否则「连不上」会伪装成「服务端一个工具都没有」。
            if isinstance(data.get("error"), dict):
                err = data["error"]
                raise ToolCallError(
                    f"tools/list 失败: [{err.get('code')}] {err.get('message')}"
                )
            tools = data.get("result", {}).get("tools", [])
            return [{"name": t["name"], "description": t.get("description", ""),
                     "schema": t.get("inputSchema", {})} for t in tools]
        else:
            result = await session_info["session"].list_tools()
            return [{"name": t.name, "description": getattr(t, "description", ""),
                     "schema": getattr(t, "inputSchema", {})} for t in result.tools]

    async def validate_tools(self, server_name: str, required: Iterable[str]) -> dict:
        """启动时校验：声明的工具名是否都存在于服务端。

        这个校验把「运行时静默降级」提前成「启动即暴露」——本次事故里
        工具名错了两层（代码 + 文档）却三天没被发现，就是因为没有任何地方
        在启动时问过服务端「你到底有哪些工具」。

        刻意不在这里 fail fast：个人项目经常离线改代码/跑测试，如果校验会让
        uvicorn 起不来，第一反应是把校验删掉，那这个校验就白做了。
        硬失败交给 settings.mcp_strict_startup 开关。

        返回一个诚实的字典而不是 (bool, list)：
        **「连不上」和「工具名不对」是两件完全不同的事**，都压成 ok=False +
        missing=全部 会让离线开发时的 /health 谎报「工具名不匹配」，
        从而把人引向完全错误的排查方向。
        """
        required = sorted(set(required))
        try:
            available = sorted({t["name"] for t in await self.list_tools(server_name)})
        except Exception as e:
            logger.error("MCP tools/list 校验失败 server=%s: %s", server_name, e)
            return {
                "ok": False,
                "server": server_name,
                "reason": "unreachable",
                "required": required,
                "missing": [],
                "available": [],
                "error": f"{type(e).__name__}: {e}",
            }

        missing = sorted(set(required) - set(available))
        if missing:
            logger.critical(
                "MCP 工具名不匹配！server=%s 缺失=%s 服务端实际提供=%s",
                server_name,
                missing,
                available,
            )
        else:
            logger.info(
                "MCP 工具清单校验通过 server=%s 共 %d 个工具", server_name, len(available)
            )
        return {
            "ok": not missing,
            "server": server_name,
            "reason": None if not missing else "tool_name_mismatch",
            "required": required,
            "missing": missing,
            "available": available,
            "error": None,
        }

    async def _get_session(self, server_name: str) -> dict:
        if server_name not in self._sessions:
            await self.connect(server_name)
        return self._sessions[server_name]

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        for info in self._sessions.values():
            if info["type"] == "stdio":
                try:
                    await info["session"].__aexit__(None, None, None)
                except Exception:
                    pass
        self._sessions.clear()
