"""
工具契约测试 —— 桩掉 MCP 客户端，喂真实夹具，零网络。

这一层是整条链路的**验收面**：前面三层（工具名、客户端错误判定、解析层）
修得对不对，最终都体现为「工具返回给 LLM 的那个 JSON 串对不对」。

断言三件事：
  1. 调用的**工具名**正确  —— 第 1 层 bug 的永久防线
  2. items 里**有真实字段** —— 第 3/4 层 bug（旧实现每条都是 {"name": null}）
  3. 失败时返回**结构化错误信封**，且宽泛 catch 已删除、异常能冒出去
"""

import json

import pytest

from app.core.exceptions import ToolCallError
from app.graph import tools as tools_module
from app.graph.tools import (
    TC_HOTEL,
    TC_RESTAURANT,
    _match_typecode,
    get_weather_and_climate,
    search_hotels,
    search_restaurants,
    search_travel_inspiration,
)
from app.mcp.client import MCPToolResult, _classify_rpc_error
from conftest import load_fixture


# ---------- 打桩 ----------


class FakeMCP:
    """记录调用参数并返回预设结果的 MCP 客户端替身。"""

    def __init__(self, result=None, exc=None):
        self.calls: list[tuple] = []
        self._result = result
        self._exc = exc

    async def call_tool(self, server_name, tool_name, arguments):
        self.calls.append((server_name, tool_name, arguments))
        if self._exc is not None:
            raise self._exc
        return self._result


@pytest.fixture
def install_mcp(monkeypatch):
    def _install(result=None, exc=None) -> FakeMCP:
        fake = FakeMCP(result, exc)
        monkeypatch.setattr(tools_module, "mcp_client", fake)
        return fake

    return _install


def _ok_from_fixture(name: str) -> MCPToolResult:
    """把抓下来的真实响应包成客户端会返回的成功结果。"""
    return MCPToolResult(
        success=True, content=load_fixture(name)["result"]["content"], is_error=False
    )


def _failure_from_fixture(name: str) -> MCPToolResult:
    """用真实的 JSON-RPC 错误夹具 + 真实的分类器构造失败结果。

    刻意复用 _classify_rpc_error 而不是手写 error_code，
    否则分类器改了、这里还在断言旧值，两层会悄悄漂移。
    """
    err = load_fixture(name)["error"]
    code, retryable = _classify_rpc_error(err.get("code"), err.get("message", ""))
    return MCPToolResult(
        success=False,
        error=f"[{err.get('code')}] {err.get('message')}",
        error_code=code,
        retryable=retryable,
    )


async def _call(tool, **kwargs) -> dict:
    """四个工具都是 async，必须走 ainvoke —— invoke 会抛 NotImplementedError。"""
    return json.loads(await tool.ainvoke(kwargs))


# ---------- search_hotels ----------


async def test_search_hotels_returns_real_named_items(install_mcp):
    """核心回归：旧实现在这里每条都是 {"name": null, "address": null}。"""
    fake = install_mcp(_ok_from_fixture("amap_text_search_ok.json"))

    out = await _call(search_hotels, city="杭州市", poi_location="西湖景区")

    assert out["ok"] is True
    assert out["count"] == 5, "limit=5"
    assert out["items"], "过滤后不该为空"

    for item in out["items"]:
        assert item["name"], f"name 不能为空: {item}"
        assert item["id"], f"id 不能为空: {item}"
        assert _match_typecode(item["typecode"], TC_HOTEL), f"非住宿类漏进来了: {item['typecode']}"

    # 工具名与参数：第 1 层 bug 的防线
    server, tool_name, args = fake.calls[0]
    assert server == "amap"
    assert tool_name == "maps_text_search"
    assert "西湖景区" in args["keywords"]
    assert args["citylimit"] is True
    assert args["city"] == "杭州市"


async def test_search_hotels_drops_non_lodging(install_mcp):
    """夹具 20 条里只有 11 条是住宿类，公厕/停车场不许出现。"""
    install_mcp(_ok_from_fixture("amap_text_search_ok.json"))

    out = await _call(search_hotels, city="杭州市", poi_location="西湖景区")

    assert not any(i["typecode"].startswith(("20", "15")) for i in out["items"])
    assert out["notice"], "裁剪过就必须告知 LLM"


@pytest.mark.parametrize("profile,expected", [("经济型", "连锁酒店"), ("民宿", "山间民宿")])
async def test_hotel_search_does_not_label_homestays_as_economic_hotels(
    install_mcp, profile, expected
):
    install_mcp(
        MCPToolResult(
            success=True,
            content=[
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "pois": [
                                {"id": "h1", "name": "山间民宿", "typecode": "100400"},
                                {"id": "h2", "name": "连锁酒店", "typecode": "100100"},
                            ]
                        }
                    ),
                }
            ],
        )
    )
    out = await _call(search_hotels, city="杭州", poi_location="西湖", budget_level=profile)
    assert [item["name"] for item in out["items"]] == [expected]


async def test_snack_search_keeps_the_specific_food_query(install_mcp):
    fake = install_mcp(_ok_from_fixture("amap_empty_pois.json"))
    await _call(search_restaurants, city="杭州", poi_location="湖滨", food_type="葱包桧小吃")
    assert fake.calls[0][2]["keywords"] == "湖滨 葱包桧小吃"


async def test_search_hotels_reports_empty_as_ok_not_error(install_mcp):
    """搜不到的语义是「成功但为空」，不是「失败」——这个区分就是本次事故的根因。"""
    install_mcp(_ok_from_fixture("amap_empty_pois.json"))

    out = await _call(search_hotels, city="杭州市", poi_location="不存在的地方")

    assert out["ok"] is True
    assert out["count"] == 0
    assert out["items"] == []
    assert "notice" in out, "空结果必须带提示，否则 LLM 会无限重试"
    assert "error" not in out


# ---------- 失败信封 ----------


async def test_tool_not_found_is_non_retryable(install_mcp):
    """第 1 层 bug 的端到端回归：工具名不存在的错误必须传到 LLM 眼前。"""
    install_mcp(_failure_from_fixture("amap_tool_not_found.json"))

    out = await _call(get_weather_and_climate, city="杭州市")

    assert out["ok"] is False
    err = out["error"]
    assert err["code"] == "tool_not_found"
    assert err["retryable"] is False
    assert err["hint"], "必须给出祈使句提示，模型对祈使句的遵守度高于布尔值"
    assert "禁止重试" in err["hint"]


async def test_config_error_is_returned_not_raised(install_mcp):
    """ToolCallError 是本地配置类错误，应当被接住并变成信封。"""
    install_mcp(exc=ToolCallError("未配置 MCP Server: amap"))

    out = await _call(search_hotels, city="杭州市", poi_location="西湖景区")

    assert out["ok"] is False
    assert out["error"]["code"] == "config_error"
    assert out["error"]["retryable"] is False


async def test_unexpected_exception_propagates(install_mcp):
    """非配置类异常必须冒出去，不许被宽泛 catch 吞掉。

    旧实现在四个工具里各写了一个 except Exception，把任何异常都降级成
    「返回空字符串」，那是第 2 层 bug 的最后一道掩护。这条测试钉住它的删除。
    """
    install_mcp(exc=RuntimeError("模拟未预期故障"))

    with pytest.raises(RuntimeError, match="模拟未预期故障"):
        await search_hotels.ainvoke({"city": "杭州市", "poi_location": "西湖景区"})


# ---------- search_restaurants ----------


async def test_search_restaurants_filters_to_dining(install_mcp):
    install_mcp(_ok_from_fixture("amap_text_search_ok.json"))

    out = await _call(search_restaurants, city="杭州市", poi_location="西湖景区")

    assert out["ok"] is True
    assert out["items"], "夹具里有 050700 咖啡茶饮，不该被过滤空"
    assert all(_match_typecode(i["typecode"], TC_RESTAURANT) for i in out["items"]), (
        f"非餐饮类漏进来了: {[i['typecode'] for i in out['items']]}"
    )


# ---------- search_travel_inspiration ----------


async def test_search_travel_inspiration_does_not_filter_by_type(install_mcp):
    """本工具刻意不过滤：博物馆在 140000 不在 110000，过滤会删掉用户明确要的博物馆。"""
    install_mcp(_ok_from_fixture("amap_text_search_ok.json"))

    out = await _call(search_travel_inspiration, city="杭州市", keywords="西湖", max_results=100)

    assert out["ok"] is True
    assert out["count"] == 20, "不过滤就应拿到全部 20 条"
    assert "notice" not in out, "没裁剪就不该有 notice"


# ---------- get_weather_and_climate ----------


async def test_weather_returns_forecasts(install_mcp):
    fake = install_mcp(_ok_from_fixture("amap_weather_ok.json"))

    out = await _call(get_weather_and_climate, city="杭州市")

    assert out["ok"] is True
    assert out["city"] == "杭州市"
    assert out["count"] > 0
    first = out["items"][0]
    assert first["date"] and first["dayweather"]
    assert "daytemp_float" not in first, "白名单外的冗余字段应被剔除"

    assert fake.calls[0][1] == "maps_weather"
    assert fake.calls[0][2] == {"city": "杭州市"}


async def test_weather_unparseable_is_ok_with_notice(install_mcp):
    """响应结构变了也不能报 failure —— 那是「解析不出来」，不是「调用失败」。"""
    install_mcp(MCPToolResult(success=True, content=[], is_error=False))

    out = await _call(get_weather_and_climate, city="杭州市")

    assert out["ok"] is True
    assert out["count"] == 0
    assert "notice" in out


@pytest.mark.parametrize("marker", ["建设中", "装修中", "暂停营业", "已关闭", "尚未开业"])
def test_explicitly_unavailable_pois_never_enter_candidates(marker):
    from app.graph.tools import _normalize_poi

    assert _normalize_poi({"id": "bad", "name": f"喀纳斯酒店({marker})"}) is None
    assert _normalize_poi({"id": "ok", "name": "普通酒店"})["name"] == "普通酒店"


@pytest.mark.parametrize("profile,expected", [("中档", ["hotel"]), ("民宿", ["stay"])])
async def test_route_nearby_preserves_lodging_direction_before_truncation(
    install_mcp, profile, expected
):
    from app.graph.tools import search_nearby_pois

    pois = [
        {"id": "stay", "name": "真实民宿", "address": "西湖区", "typecode": "100000"},
        {"id": "hotel", "name": "真实酒店", "address": "西湖区", "typecode": "100000"},
    ]
    fake = install_mcp(
        MCPToolResult(
            success=True,
            content=[{"type": "text", "text": json.dumps({"pois": pois})}],
            is_error=False,
        )
    )
    out = await _call(
        search_nearby_pois,
        city="杭州市",
        location="120.14,30.24",
        category="hotel",
        hotel_profile=profile,
    )
    assert [item["id"] for item in out["items"]] == expected
    assert fake.calls[0][2]["radius"] == "5000"
    assert "hotel_profile" not in fake.calls[0][2]
