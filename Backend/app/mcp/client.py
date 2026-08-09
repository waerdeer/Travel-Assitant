import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from app.core.exceptions import ToolCallError


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
    success: bool
    content: Any = None
    error: Optional[str] = None
    is_error: bool = False


class MCPClient:
    """统一管理多个外部 MCP Server 的连接与工具调用。

    支持两种传输模式:
      - http: 直接通过 HTTP 调用远程 MCP Server（推荐，无需本地依赖）
      - stdio: 启动本地子进程（需要 Node.js / Python 等运行时）

    用法:
        client = MCPClient()
        await client.load_config("app/mcp/servers.json")
        result = await client.call_tool("amap", "amap_maps_text_search", {
            "keywords": "景点", "city": "北京"
        })
        await client.close()
    """

    def __init__(self):
        self._sessions: dict[str, Any] = {}
        self._servers: dict[str, MCPServerConfig] = {}
        self._http_client: Optional[httpx.AsyncClient] = None

    def _resolve_env(self, raw: dict[str, str]) -> dict[str, str]:
        resolved = {}
        for key, value in raw.items():
            if value.startswith("${") and value.endswith("}"):
                resolved[key] = os.environ.get(value[2:-1], "")
            else:
                resolved[key] = value
        return resolved

    def _resolve_url(self, url: str) -> str:
        if "${" in url:
            for match in set(__import__("re").findall(r"\$\{(\w+)\}", url)):
                url = url.replace(f"${{{match}}}", os.environ.get(match, ""))
        return url

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
            self._http_client = httpx.AsyncClient(timeout=60)
        return self._http_client

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> MCPToolResult:
        session_info = await self._get_session(server_name)

        if session_info["type"] == "http":
            return await self._call_tool_http(session_info["url"], tool_name, arguments)
        else:
            return await self._call_tool_stdio(session_info["session"], tool_name, arguments)

    async def _call_tool_http(self, url: str, tool_name: str, arguments: dict) -> MCPToolResult:
        client = self._get_http_client()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", {})
            content = result.get("content", [])
            is_error = result.get("isError", False)
            return MCPToolResult(success=True, content=content, is_error=is_error)
        except Exception as e:
            return MCPToolResult(success=False, error=str(e))

    async def _call_tool_stdio(self, session, tool_name: str, arguments: dict) -> MCPToolResult:
        result = await session.call_tool(tool_name, arguments)
        content = result.content if hasattr(result, "content") else result
        return MCPToolResult(
            success=True,
            content=content,
            is_error=bool(getattr(result, "isError", False)),
        )

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
            resp = await client.post(session_info["url"], json=payload)
            data = resp.json()
            tools = data.get("result", {}).get("tools", [])
            return [{"name": t["name"], "description": t.get("description", ""),
                     "schema": t.get("inputSchema", {})} for t in tools]
        else:
            result = await session_info["session"].list_tools()
            return [{"name": t.name, "description": getattr(t, "description", ""),
                     "schema": getattr(t, "inputSchema", {})} for t in result.tools]

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
