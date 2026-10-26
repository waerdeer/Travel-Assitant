"""真实高德 MCP 的集成测试。

只写**结构性不变量**，绝不写具体的 POI 名称或数量 ——
实测同一个关键词在不同时刻返回的构成会变，写死内容只会制造脆弱的测试。
"""

import json

import pytest

from app.graph.tools import (
    AMAP_REQUIRED_TOOLS,
    AMAP_SERVER,
    TOOL_WEATHER,
    get_weather_and_climate,
    search_hotels,
    search_restaurants,
    search_travel_inspiration,
)
from app.mcp.registry import mcp_client

pytestmark = pytest.mark.integration


async def _load_client():
    import os

    config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "mcp", "servers.json"
    )
    await mcp_client.load_config(os.path.abspath(config_path))
    return mcp_client


async def test_declared_tool_names_exist_on_server():
    """第 1 层 bug 的线上版防线：我们声明的工具名，服务端真的提供。"""
    health = await (await _load_client()).validate_tools(
        AMAP_SERVER, AMAP_REQUIRED_TOOLS
    )
    assert health["reason"] != "unreachable", f"连不上高德 MCP: {health['error']}"
    assert health["ok"], (
        f"工具名不匹配！缺失={health['missing']} 服务端实际提供={health['available']}"
    )


async def test_weather_returns_real_forecasts():
    await _load_client()
    out = json.loads(await get_weather_and_climate.ainvoke({"city": "杭州市"}))

    assert out["ok"] is True, f"天气工具失败: {out}"
    assert out["count"] > 0
    first = out["items"][0]
    assert first["date"] and first["dayweather"]


async def test_hotels_returns_named_lodging():
    """核心回归：旧实现在这里每一条都是 {"name": null}。"""
    await _load_client()
    out = json.loads(
        await search_hotels.ainvoke({"city": "杭州市", "poi_location": "西湖景区"})
    )

    assert out["ok"] is True, f"酒店工具失败: {out}"
    for item in out["items"]:
        assert item["name"], f"name 为空: {item}"
        assert item["id"], f"id 为空: {item}"


async def test_inspiration_returns_named_pois():
    await _load_client()
    out = json.loads(
        await search_travel_inspiration.ainvoke(
            {"city": "杭州市", "keywords": "博物馆", "max_results": 5}
        )
    )

    assert out["ok"] is True, f"景点工具失败: {out}"
    for item in out["items"]:
        assert item["name"]


async def test_restaurants_returns_dining():
    await _load_client()
    out = json.loads(
        await search_restaurants.ainvoke(
            {"city": "杭州市", "poi_location": "西湖景区", "food_type": "当地特色"}
        )
    )

    assert out["ok"] is True, f"餐厅工具失败: {out}"
    for item in out["items"]:
        assert item["name"]


async def test_unknown_tool_name_surfaces_as_error():
    """把工具名故意写错，必须拿到 ok=false —— 这正是整次事故起点的线上验证。"""
    from app.graph.tools import _error_payload
    from app.mcp.client import MCPToolResult

    result = await (await _load_client()).call_tool(
        AMAP_SERVER, "amap_maps_weather", {"city": "杭州市"}
    )
    assert result.success is False
    assert result.error_code == "tool_not_found"
    assert result.retryable is False

    payload = json.loads(_error_payload("amap_maps_weather", result))
    assert payload["ok"] is False
    assert payload["error"]["retryable"] is False
