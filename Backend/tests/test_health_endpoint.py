"""
/health 与启动校验的接线测试 —— 零网络。

背景：
    旧版 /health 永远返回 {"status": "ok"}，而当时四个工具全在返回空数据、
    三张表全是 0 行。这个端点在那段时间里持续报告「一切正常」，是
    「UI 完全正常、不报错」这个最恶劣特性的一个缩影。

这里用 TestClient 作为上下文管理器，它会真正跑一遍 lifespan ——
所以测的是「启动校验的结果有没有接进 /health」，而不是 validate_tools 本身
（那个逻辑在 test_mcp_client_errors.py 里单独测）。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.mcp.registry import mcp_client


@pytest.fixture
def client(monkeypatch):
    """返回一个能注入假校验结果的 TestClient 工厂。"""

    def _run(health: dict):
        async def fake_validate(server_name, required):
            return health

        # main.py 里是 `from app.mcp.registry import mcp_client`，
        # 拿到的是同一个对象，所以替换实例方法即可同时作用于两边。
        monkeypatch.setattr(mcp_client, "validate_tools", fake_validate)
        return TestClient(app)

    return _run


def test_health_ok_when_tools_match(client):
    with client(
        {
            "ok": True,
            "server": "amap",
            "reason": None,
            "required": ["maps_weather"],
            "missing": [],
            "available": ["maps_weather"],
            "error": None,
        }
    ) as c:
        body = c.get("/health").json()

    assert body["status"] == "ok"
    assert body["mcp_health"]["ok"] is True
    assert body["mcp_health"]["missing"] == []


def test_health_degraded_on_tool_name_mismatch(client):
    """验收标准：故意改错工具名，/health 必须变成非 ok。"""
    with client(
        {
            "ok": False,
            "server": "amap",
            "reason": "tool_name_mismatch",
            "required": ["maps_weather", "amap_maps_text_search"],
            "missing": ["amap_maps_text_search"],
            "available": ["maps_weather"],
            "error": None,
        }
    ) as c:
        body = c.get("/health").json()

    assert body["status"] == "degraded"
    assert body["mcp_health"]["ok"] is False
    assert body["mcp_health"]["reason"] == "tool_name_mismatch"
    assert body["mcp_health"]["missing"] == ["amap_maps_text_search"]


def test_health_degraded_when_mcp_unreachable(client):
    """离线开发时也是 degraded，但 reason 必须是 unreachable 而不是 mismatch。"""
    with client(
        {
            "ok": False,
            "server": "amap",
            "reason": "unreachable",
            "required": ["maps_weather"],
            "missing": [],
            "available": [],
            "error": "ConnectError: no route to host",
        }
    ) as c:
        body = c.get("/health").json()

    assert body["status"] == "degraded"
    assert body["mcp_health"]["reason"] == "unreachable"
    assert body["mcp_health"]["missing"] == []
