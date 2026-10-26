"""
MCP 客户端错误处理测试 —— 用 httpx 自带的 MockTransport，零网络。

背景（第 2 层 bug，最阴的一层）：
    _call_tool_http 曾经是：
        data = self._parse_sse_or_json(resp)
        result = data.get("result", {})        # 响应里是 "error" 键，不是 "result"
        content = result.get("content", [])    # 于是拿到 {}
        return MCPToolResult(success=True, content=content, is_error=is_error)
    服务端明确报 Tool not found，客户端却返回 success=True / content=[]。
    它让第 1 层（工具名写错）永远暴露不出来 —— 这层不修，修了工具名也不知道对不对。
"""

import httpx
import pytest

from app.mcp.client import MCPClient, MCPServerConfig, _classify_rpc_error
from conftest import load_fixture


def _register(client: MCPClient) -> MCPClient:
    """注册一个 amap server，让 validate_tools 这类走 _get_session 的路径能跑通。"""
    client._servers["amap"] = MCPServerConfig(
        name="amap", transport="http", url="http://x/mcp"
    )
    return client


def _client(payload: dict, status_code: int = 200) -> MCPClient:
    """构造一个用 MockTransport 打桩的客户端，不产生任何真实网络请求。"""
    client = MCPClient()
    client._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status_code, json=payload)
        )
    )
    return _register(client)


def _client_raw(body: str, status_code: int = 200, content_type: str = "application/json"):
    client = MCPClient()
    client._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status_code, text=body, headers={"content-type": content_type}
            )
        )
    )
    return _register(client)


def _unreachable_client() -> MCPClient:
    client = MCPClient()
    client._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("no route to host"))
        )
    )
    return _register(client)


# ---------- 本次事故的回归测试 ----------


async def test_jsonrpc_error_is_reported_as_failure():
    """服务端报 Tool not found 时，客户端必须返回 success=False。

    这是整次事故的核心回归测试：旧实现在这里返回 success=True。
    """
    payload = load_fixture("amap_tool_not_found.json")
    result = await _client(payload)._call_tool_http(
        "http://x/mcp", "amap_maps_weather", {"city": "杭州市"}
    )
    assert result.success is False
    assert result.error_code == "tool_not_found"
    assert result.retryable is False
    assert "Tool not found" in result.error


async def test_missing_result_key_is_failure():
    """响应既没有 error 也没有 result —— 不能当成「成功但为空」。"""
    result = await _client({"jsonrpc": "2.0", "id": 1})._call_tool_http(
        "http://x/mcp", "maps_weather", {}
    )
    assert result.success is False
    assert result.error_code == "protocol_error"


async def test_non_jsonrpc_envelope_is_failure():
    """不是 JSON-RPC 信封（网关错误页 / 业务错误体）也要判失败。"""
    result = await _client(
        {"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}
    )._call_tool_http("http://x/mcp", "maps_weather", {})
    assert result.success is False
    assert result.error_code == "protocol_error"
    assert "INVALID_USER_KEY" in result.error


async def test_is_error_flag_is_failure():
    """result.isError=true 是业务失败，错误信息取自 content 里的文本。"""
    result = await _client(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": "参数 city 必填"}],
            },
        }
    )._call_tool_http("http://x/mcp", "maps_weather", {})
    assert result.success is False
    assert result.error_code == "tool_error"
    assert "参数 city 必填" in result.error


async def test_empty_body_is_failure():
    result = await _client_raw("")._call_tool_http("http://x/mcp", "maps_weather", {})
    assert result.success is False
    assert result.error_code == "empty_response"
    assert result.retryable is True  # 空响应可能是瞬时故障


async def test_malformed_json_is_failure():
    result = await _client_raw("{not json")._call_tool_http(
        "http://x/mcp", "maps_weather", {}
    )
    assert result.success is False
    assert result.error_code == "protocol_error"


async def test_http_500_is_retryable():
    result = await _client({"boom": True}, status_code=500)._call_tool_http(
        "http://x/mcp", "maps_weather", {}
    )
    assert result.success is False
    assert result.error_code == "http_error"
    assert result.retryable is True


async def test_http_400_is_not_retryable():
    result = await _client({"bad": True}, status_code=400)._call_tool_http(
        "http://x/mcp", "maps_weather", {}
    )
    assert result.success is False
    assert result.retryable is False


# ---------- 成功路径不能被误伤 ----------


async def test_successful_call_still_succeeds():
    payload = load_fixture("amap_weather_ok.json")
    envelope = {"jsonrpc": "2.0", "id": 1, "result": payload["result"]}
    result = await _client(envelope)._call_tool_http(
        "http://x/mcp", "maps_weather", {"city": "杭州市"}
    )
    assert result.success is True
    assert result.is_error is False
    assert result.content  # 有实际内容


# ---------- SSE 分支 ----------


async def test_sse_response_is_parsed():
    body = 'data: {"jsonrpc":"2.0","id":1,"result":{"content":[]}}\n\n'
    result = await _client_raw(body, content_type="text/event-stream")._call_tool_http(
        "http://x/mcp", "maps_weather", {}
    )
    assert result.success is True


async def test_sse_without_data_line_is_failure():
    """SSE 里没有 data 行时必须报错，不能 return {} 伪装成空响应。"""
    result = await _client_raw(
        "event: ping\n\n", content_type="text/event-stream"
    )._call_tool_http("http://x/mcp", "maps_weather", {})
    assert result.success is False
    assert result.error_code == "protocol_error"


# ---------- 错误分类表 ----------


@pytest.mark.parametrize(
    "code,message,expected_code,expected_retryable",
    [
        (-32601, "Method not found", "tool_not_found", False),
        (-32603, "Tool not found: amap_maps_weather", "tool_not_found", False),
        (-32602, "Invalid params", "invalid_params", False),
        (-32603, "Internal error", "server_error", True),
        (-32000, "Server error", "server_error", True),
        (None, "Connection timed out", "server_error", True),
        (None, "rate limit exceeded", "server_error", True),
        (None, "某种没见过的错误", "rpc_error", False),
    ],
)
def test_error_classification(code, message, expected_code, expected_retryable):
    assert _classify_rpc_error(code, message) == (expected_code, expected_retryable)


# ---------- 启动校验 validate_tools ----------


async def test_validate_tools_passes_on_real_manifest():
    """用抓下来的真实工具清单校验，声明的工具名必须全部存在。"""
    from app.graph.tools import AMAP_REQUIRED_TOOLS

    payload = {"jsonrpc": "2.0", "id": 1, "result": load_fixture("amap_tools_list.json")["result"]}
    health = await _client(payload).validate_tools("amap", AMAP_REQUIRED_TOOLS)

    assert health["ok"] is True
    assert health["reason"] is None
    assert health["missing"] == []
    assert "maps_weather" in health["available"]


async def test_validate_tools_reports_name_mismatch():
    """工具名写错时必须报 tool_name_mismatch，并列出服务端实际有哪些。"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": "maps_weather", "inputSchema": {}}]},
    }
    health = await _client(payload).validate_tools(
        "amap", ("maps_weather", "amap_maps_text_search")
    )

    assert health["ok"] is False
    assert health["reason"] == "tool_name_mismatch"
    assert health["missing"] == ["amap_maps_text_search"]


async def test_validate_tools_distinguishes_unreachable_from_mismatch():
    """连不上和工具名不对是两件事，不能都压成 ok=False + missing=全部。

    混为一谈会让离线开发时的 /health 谎报「工具名不匹配」，
    把人引向完全错误的排查方向。
    """
    health = await _unreachable_client().validate_tools("amap", ("maps_weather",))

    assert health["ok"] is False
    assert health["reason"] == "unreachable"
    assert health["missing"] == [], "连不上时不该谎报缺工具"
    assert "ConnectError" in health["error"]
