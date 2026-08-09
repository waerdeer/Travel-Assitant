"""
=====================================================================
模块名称: registry.py
功能描述: MCP (Model Context Protocol) 注册表，负责管理和注册项目中接入的各种 MCP Server。
=====================================================================
"""

from app.mcp.client import MCPClient, MCPToolResult, MCPServerConfig

mcp_client = MCPClient()

__all__ = [
    "mcp_client",
    "MCPClient",
    "MCPToolResult",
    "MCPServerConfig",
]