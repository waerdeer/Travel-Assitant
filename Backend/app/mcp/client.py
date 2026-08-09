"""
=====================================================================
模块名称: client.py
功能描述: MCP 客户端，用于和底层的 MCP 服务进行标准化通信和工具调用。
=====================================================================
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

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

    def _env(self, raw: dict[str, str]) -> dict[str, str]:
        """把 \"${AMAP_API_KEY}\" 这样的占位符替换成真实环境变量"""
        resolved = {}
        for key, value in raw.items():
            if value.startswith("${") and value.endswith("}"):
                resolved[key] = os.environ.get(value[2:-1], "")
            else:
                resolved[key] = value
        return resolved

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

    def _import_sdk(self) -> Any:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            return (ClientSession, StdioServerParameters, stdio_client)
        except ImportError as e:
            raise ToolCallError(
                "缺少 mcp SDK，请先安装 Python 3.10+ 并执行: pip install mcp"
            ) from e

    async def connect(self, server_name: str) -> None:
        if server_name in self._sessions:
            return
        cfg = self._servers.get(server_name)
        if cfg is None:
            raise ToolCallError(f"未配置 MCP Server: {server_name}")

        ClientSession, StdioServerParameters, stdio_client = self._import_sdk()
        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=self._env(cfg.env),
        )
        session = await self._connect_stdio(ClientSession, stdio_client, params)
        self._sessions[server_name] = session

    async def _connect_stdio(self, ClientSession, stdio_client, params) -> Any:
        async with stdio_client(params) as (read, write):
            session = ClientSession(read, write)
            await session.initialize()
            return session

    async def list_tools(self, server_name: str) -> list[dict]:
        session = await self.session(server_name)
        result = await session.list_tools()
        return [{"name": t.name, "description": getattr(t, "description", ""),
                 "schema": getattr(t, "inputSchema", {})} for t in result.tools]

    async def session(self, server_name: str) -> Any:
        if server_name not in self._sessions:
            await self.connect(server_name)
        return self._sessions[server_name]

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> MCPToolResult:
        session = await self.session(server_name)
        result = await session.call_tool(tool_name, arguments)
        content = result.content if hasattr(result, "content") else result
        return MCPToolResult(
            success=True,
            content=content,
            is_error=bool(getattr(result, "isError", False)),
        )

    async def close(self) -> None:
        for session in self._sessions.values():
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
        self._sessions.clear()