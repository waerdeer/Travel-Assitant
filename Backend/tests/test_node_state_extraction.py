"""
节点出参提取测试 —— 桩掉 ReAct，零网络。

这是 B 方案（取消提炼 LLM）的核心回归面。

背景：
    info_agent / booking_node 原本在 ReAct 之后再调一次 LLM，让它把自己写的
    散文「提炼」回结构化数据。而该端点的 with_structured_output 必然 400
    （This response_format type is unavailable now），于是每次提炼都失败、
    每次都把已经拿到手的数据置空 —— 实测真实请求里天气能进最终行程单
    （因为工具真的调通了），景点和酒店却全是空的。

    数据从来没有丢失的风险，是这条链路自己把它弄丢的。现在直接从
    ToolMessage 的 JSON 信封取数，这条损失链路整个消失。

本文件里最重要的断言是最后两条：
    state 里的每个名称都必须来自工具返回的 items，**模型散文里出现但工具
    没返回过的名称一律不许进 state**。
这把「不许幻觉」从 prompt 里的祈求和变成可执行的断言。
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.graph import nodes as nodes_module
from app.graph import tools as tools_module
from app.graph.tools import (
    TOOL_TEXT_SEARCH,
    TOOL_WEATHER,
    get_weather_and_climate,
    search_hotels,
    search_travel_inspiration,
)
from app.mcp.client import MCPToolResult, _classify_rpc_error
from conftest import load_fixture


# ---------- 打桩 ----------


class FakeMCP:
    """返回真实夹具内容的 MCP 客户端替身，记录调用参数。"""

    def __init__(self, fixture_name: str):
        self.fixture_name = fixture_name
        self.calls: list[tuple] = []

    async def call_tool(self, server_name, tool_name, arguments):
        self.calls.append((server_name, tool_name, arguments))
        return MCPToolResult(
            success=True,
            content=load_fixture(self.fixture_name)["result"]["content"],
            is_error=False,
        )


@pytest.fixture
def install_mcp(monkeypatch):
    def _install(fixture_name: str) -> FakeMCP:
        fake = FakeMCP(fixture_name)
        monkeypatch.setattr(tools_module, "mcp_client", fake)
        return fake

    return _install


async def _weather_envelope(install_mcp) -> dict:
    """跑一次真实的天气工具，拿它实际产出的信封。"""
    install_mcp("amap_weather_ok.json")
    return json.loads(await get_weather_and_climate.ainvoke({"city": "杭州市"}))


async def _search_envelope(install_mcp) -> dict:
    install_mcp("amap_text_search_ok.json")
    return json.loads(
        await search_travel_inspiration.ainvoke(
            {"city": "杭州市", "keywords": "博物馆", "max_results": 5}
        )
    )


def _tool_message(envelope: dict, tool_name: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(envelope, ensure_ascii=False),
        tool_call_id="call_1",
        name=tool_name,
    )


def _stub_react(monkeypatch, text: str, payloads: list):
    """把 _run_react 换成直接返回 (文本, 错误, 信封列表)。

    info_agent / booking_node 自身不再调用任何 LLM，所以桩掉这一个函数
    就足以让整个节点离线可测。
    """
    captured = {}

    async def fake_run_react(*, tools, sys_prompt, state, kickoff, node_name):
        captured["tools"] = tools
        captured["sys_prompt"] = sys_prompt
        captured["node_name"] = node_name
        return text, None, payloads

    monkeypatch.setattr(nodes_module, "_run_react", fake_run_react)
    return captured


# ---------- _collect_tool_payloads ----------


def test_collects_only_tool_envelopes():
    messages = [
        AIMessage(content="我先查天气"),
        _tool_message({"ok": True, "count": 1, "items": [{"name": "A"}]}, TOOL_WEATHER),
        AIMessage(content="这是模型的自然语言回复，不是工具结果"),
    ]
    payloads = nodes_module._collect_tool_payloads(messages)

    assert len(payloads) == 1
    assert payloads[0]["tool"] == TOOL_WEATHER
    assert payloads[0]["ok"] is True


def test_skips_unparseable_and_plain_text_messages():
    """解析不了的消息必须安静跳过，而不是抛异常打断整轮。"""
    messages = [
        ToolMessage(content="服务暂不可用", tool_call_id="c", name="x"),
        ToolMessage(content="{不是 json", tool_call_id="c", name="x"),
        ToolMessage(content='{"no_ok_field": 1}', tool_call_id="c", name="x"),
        ToolMessage(content=None, tool_call_id="c", name="x"),
    ]
    assert nodes_module._collect_tool_payloads(messages) == []


async def test_collects_real_envelopes(install_mcp):
    envelope = await _search_envelope(install_mcp)
    payloads = nodes_module._collect_tool_payloads(
        [_tool_message(envelope, TOOL_TEXT_SEARCH)]
    )
    assert payloads[0]["tool"] == TOOL_TEXT_SEARCH
    assert payloads[0]["items"], "真实夹具必须能解析出 items"


# ---------- _items_from_tool ----------


def test_items_from_tool_reads_items():
    payloads = [
        {
            "tool": get_weather_and_climate.name,
            "ok": True,
            "count": 2,
            "items": [{"name": "晴"}],
        },
        {
            "tool": search_travel_inspiration.name,
            "ok": True,
            "count": 1,
            "items": [{"id": "B1", "name": "博物馆"}],
        },
    ]
    assert nodes_module._items_from_tool(payloads, search_travel_inspiration) == [
        {"id": "B1", "name": "博物馆"}
    ]


def test_tool_tag_is_langchain_name_not_mcp_name():
    """**回归**：过滤必须按 LangChain 工具名，不是 MCP 服务端工具名。

    真实故障：ToolMessage.name 是 'get_weather_and_climate'（ToolNode 从
    tool_call 原样抄过来的 @tool 函数名），而过滤条件写的是 MCP 名
    'maps_weather'。结果日志里明明打印「解析出信封 3 个」，取出来的却是
    0 条 —— 信封收到了，却一条都没匹配上，而且不报错。

    这条断言把两个名字空间钉死，防止再被混用。
    """
    assert get_weather_and_climate.name != TOOL_WEATHER
    assert search_travel_inspiration.name != TOOL_TEXT_SEARCH

    # 消息上记的是 LangChain 名，按它取得到；按 MCP 名取不到。
    payload = {
        "tool": get_weather_and_climate.name,
        "ok": True,
        "items": [{"name": "晴"}],
    }
    assert nodes_module._items_from_tool([payload], get_weather_and_climate)
    assert nodes_module._items_from_tool([payload], TOOL_WEATHER) == []


def test_two_text_search_tools_do_not_bleed_into_each_other():
    """景点和酒店底层调的是同一个 maps_text_search，但必须各归各的。

    这正是按 MCP 名过滤做不到的事：两个工具的信封会互相污染。
    """
    payloads = [
        {"tool": search_travel_inspiration.name, "ok": True, "items": [{"name": "博物馆"}]},
        {"tool": search_hotels.name, "ok": True, "items": [{"name": "某酒店"}]},
    ]
    assert [i["name"] for i in nodes_module._items_from_tool(payloads, search_hotels)] == [
        "某酒店"
    ]
    assert [
        i["name"] for i in nodes_module._items_from_tool(payloads, search_travel_inspiration)
    ] == ["博物馆"]


def test_failed_envelope_contributes_no_items():
    """ok=false 是失败，不许变成空数据混进 state。"""
    payloads = [
        {
            "tool": search_travel_inspiration.name,
            "ok": False,
            "error": {"code": "tool_not_found"},
        }
    ]
    assert nodes_module._items_from_tool(payloads, search_travel_inspiration) == []


def test_merges_repeated_calls_and_dedupes():
    """TOOL_POLICY 允许同一工具调 2 次：两次的真实结果都该留下，但不许重复。"""
    name = search_travel_inspiration.name
    payloads = [
        {"tool": name, "ok": True, "items": [{"id": "B1", "name": "甲"}]},
        {
            "tool": name,
            "ok": True,
            "items": [{"id": "B1", "name": "甲"}, {"id": "B2", "name": "乙"}],
        },
    ]
    items = nodes_module._items_from_tool(payloads, search_travel_inspiration)
    assert [i["id"] for i in items] == ["B1", "B2"]


def test_items_without_id_dedupe_by_name():
    name = search_travel_inspiration.name
    payloads = [
        {"tool": name, "ok": True, "items": [{"name": "甲"}]},
        {"tool": name, "ok": True, "items": [{"name": "甲"}]},
    ]
    assert len(nodes_module._items_from_tool(payloads, search_travel_inspiration)) == 1


def test_empty_success_envelope_yields_empty():
    payloads = [
        {
            "tool": search_travel_inspiration.name,
            "ok": True,
            "count": 0,
            "items": [],
        }
    ]
    assert nodes_module._items_from_tool(payloads, search_travel_inspiration) == []


# ---------- _last_ai_text ----------


def test_last_ai_text_takes_the_ai_message():
    messages = [
        AIMessage(content="先查一下"),
        _tool_message({"ok": True, "items": [{"name": "A"}]}, get_weather_and_climate.name),
        AIMessage(content="查完了。"),
    ]
    assert nodes_module._last_ai_text(messages) == "查完了。"


def test_last_ai_text_never_returns_a_tool_envelope():
    """planner_node 的返回值直接当行程单交付给用户。

    最后一条是 ToolMessage 时，取它会把一段 JSON 信封原文当成行程单给用户看。
    """
    envelope = {"ok": True, "count": 1, "items": [{"name": "某酒店"}]}
    messages = [
        AIMessage(content="## 行程单"),
        _tool_message(envelope, search_hotels.name),
    ]
    text = nodes_module._last_ai_text(messages)
    assert text == "## 行程单"
    assert "ok" not in text and "items" not in text


def test_last_ai_text_without_ai_message_is_empty():
    assert nodes_module._last_ai_text([]) == ""
    assert (
        nodes_module._last_ai_text(
            [_tool_message({"ok": True, "items": []}, search_hotels.name)]
        )
        == ""
    )


# ---------- _with_error ----------


def test_error_msg_accumulates_across_nodes():
    """线性图里多个节点失败时，每一条都要留下。

    实测一轮里 info_agent 和 booking_node 都失败了，前端却只收到后一条 ——
    最先坏掉的那一环反而看不见。
    """
    first = nodes_module._with_error({}, {"a": 1}, "info_agent: 天气工具未返回可用数据")
    assert first["error_msg"] == "info_agent: 天气工具未返回可用数据"

    second = nodes_module._with_error(first, {"b": 2}, "booking_node: 酒店工具未返回可用数据")
    assert "info_agent" in second["error_msg"]
    assert "booking_node" in second["error_msg"]


def test_success_does_not_write_error_msg():
    """成功必须表现为「不写这个键」，不能被 None 覆盖掉上游的错误。"""
    state = {"error_msg": "上游失败了"}
    out = nodes_module._with_error(state, {"x": 1}, None)
    assert "error_msg" not in out


# ---------- _format_weather ----------


async def test_format_weather_renders_real_envelope(install_mcp):
    envelope = await _weather_envelope(install_mcp)
    text = nodes_module._format_weather(envelope["items"])

    assert text, "真实夹具必须能渲染出内容"
    assert "℃" in text
    assert "\n" in text, "多天应逐行渲染"


@pytest.mark.parametrize("garbage", [[], None, [{}]])
def test_format_weather_handles_empty(garbage):
    """空数据渲染成空串，而不是带着一堆 None 的假预报。"""
    text = nodes_module._format_weather(garbage)
    assert "None" not in text


# ---------- _tool_failures ----------


def test_tool_failures_are_reported():
    payloads = [
        {"tool": TOOL_WEATHER, "ok": True, "items": []},
        {"tool": search_travel_inspiration.name, "ok": False, "error": {"code": "tool_not_found"}},
    ]
    assert nodes_module._tool_failures(payloads) == [
        f"{search_travel_inspiration.name}(tool_not_found)"
    ]


def test_tool_failures_from_real_error_fixture(install_mcp):
    """用真实的 JSON-RPC 错误夹具走一遍分类器，不手写 error_code。"""
    rpc_error = load_fixture("amap_tool_not_found.json")["error"]
    code, retryable = _classify_rpc_error(rpc_error["code"], rpc_error["message"])
    payloads = [
        {"tool": search_travel_inspiration.name, "ok": False, "error": {"code": code}}
    ]
    assert nodes_module._tool_failures(payloads) == [
        f"{search_travel_inspiration.name}({code})"
    ]
    assert retryable is False, "协议类失败不该被建议重试"


# ==========================================================
# info_agent：数据必须来自工具信封，而不是模型的散文
# ==========================================================


async def test_info_agent_takes_data_from_envelopes(monkeypatch, install_mcp):
    weather = await _weather_envelope(install_mcp)
    search = await _search_envelope(install_mcp)

    _stub_react(
        monkeypatch,
        text="我已查询完毕。",
        payloads=[
            {"tool": get_weather_and_climate.name, **weather},
            {"tool": search_travel_inspiration.name, **search},
        ],
    )

    out = await nodes_module.info_agent({"city": "杭州市"})

    assert out["inspiration_list"], "景点列表为空 —— 信封里有数据却没被取出来"
    assert out["weather_context"], "天气上下文为空"
    assert out.get("error_msg") is None, f"不该降级: {out.get('error_msg')}"


async def test_info_agent_state_names_are_traceable_to_tool_items(
    monkeypatch, install_mcp
):
    """**核心断言**：state 里每个名称都能在工具 items 里找到。

    这条把「不许幻觉」从 prompt 祈求变成可执行断言。
    """
    search = await _search_envelope(install_mcp)
    weather = await _weather_envelope(install_mcp)

    _stub_react(
        monkeypatch,
        text="随便写点什么。",
        payloads=[
            {"tool": get_weather_and_climate.name, **weather},
            {"tool": search_travel_inspiration.name, **search},
        ],
    )

    out = await nodes_module.info_agent({"city": "杭州市"})

    tool_names = {i["name"] for i in search["items"]}
    assert tool_names, "夹具本身没有 items，测试无意义"

    state_names = {i.get("name") for i in out["inspiration_list"]}
    assert state_names <= tool_names, (
        f"state 里出现了工具没返回过的名称（幻觉）：{state_names - tool_names}"
    )


async def test_info_agent_ignores_names_invented_in_model_prose(
    monkeypatch, install_mcp
):
    """模型散文里点名了工具没返回过的景点 —— 一个都不许进 state。

    旧实现把这段散文再喂给提炼 LLM，等于让模型给自己盖章；只要那一环
    恰好成功（或 fallback 直接透传），编造的景点就会落进 state 并进入
    最终行程单。现在数据只从 ToolMessage 走，模型说什么都不影响。
    """
    search = await _search_envelope(install_mcp)
    weather = await _weather_envelope(install_mcp)

    invented = "西湖音乐喷泉"
    assert invented not in {i["name"] for i in search["items"]}, (
        "这个名称恰好真实存在，换一个，否则断言失去意义"
    )

    _stub_react(
        monkeypatch,
        text=f"我推荐您去{invented}、灵隐寺、雷峰塔，这些都非常值得一去。",
        payloads=[
            {"tool": get_weather_and_climate.name, **weather},
            {"tool": search_travel_inspiration.name, **search},
        ],
    )

    out = await nodes_module.info_agent({"city": "杭州市"})

    state_names = {i.get("name") for i in out["inspiration_list"]}
    for fabricated in (invented, "灵隐寺", "雷峰塔"):
        assert fabricated not in state_names, f"编造的名称 {fabricated} 混进了 state"
    assert state_names, "过滤幻觉不该把真实数据也一起丢掉"


async def test_info_agent_clears_state_when_tools_return_nothing(monkeypatch):
    """工具没返回数据时 state 为空 + 显式声明降级，不许伪造。

    这行的旧实现是 `inspiration_list = [{"name": "热门景点推荐"}]` ——
    一条硬编码假数据，进了最终行程单还看不出破绽。
    """
    _stub_react(monkeypatch, text="没查到什么。", payloads=[])

    out = await nodes_module.info_agent({"city": "杭州市"})

    assert out["inspiration_list"] == [], "空就是空，不许伪造"
    assert out["weather_context"] == ""
    assert out.get("error_msg"), "数据缺口必须显式声明，否则 UI 又会「完全正常」"


async def test_info_agent_reports_tool_failure(monkeypatch, install_mcp):
    weather = await _weather_envelope(install_mcp)

    _stub_react(
        monkeypatch,
        text="景点工具挂了。",
        payloads=[
            {"tool": get_weather_and_climate.name, **weather},
            {
                "tool": search_travel_inspiration.name,
                "ok": False,
                "error": {"code": "tool_not_found"},
            },
        ],
    )

    out = await nodes_module.info_agent({"city": "杭州市"})

    assert out["inspiration_list"] == []
    assert out["weather_context"], "天气有数据就该留下，一个工具挂了不该连坐"
    assert "工具未返回可用数据" in out["error_msg"]


# ==========================================================
# booking_node：同样的契约
# ==========================================================


async def test_booking_node_uses_tool_items_not_prose(monkeypatch, install_mcp):
    hotels = await _search_envelope(install_mcp)

    _stub_react(
        monkeypatch,
        text="我推荐杭州西湖国宾馆和杭州黄龙饭店。",
        payloads=[{"tool": search_hotels.name, **hotels}],
    )

    # messages 由图里的 MessagesState 保证存在，单测必须显式喂进去：
    # booking_node 的 prompt 会读 state['messages'][-1].content 作为「用户最新消息」。
    out = await nodes_module.booking_node(
        {
            "city": "杭州市",
            "rough_itinerary": "第一天逛西湖",
            "messages": [HumanMessage(content="帮我订个酒店")],
        }
    )

    tool_names = {i["name"] for i in hotels["items"]}
    state_names = {i.get("name") for i in out["confirmed_hotels"]}
    assert state_names <= tool_names, (
        f"confirmed_hotels 里出现了工具没返回过的名称：{state_names - tool_names}"
    )
    assert state_names, "信封里有数据却没被取出来"


async def test_booking_node_carries_attractions_forward(monkeypatch, install_mcp):
    """景点从 info_agent 的结果带过来，不再由 LLM 重新发明一遍。"""
    hotels = await _search_envelope(install_mcp)
    previous = [{"name": "南宋德寿宫遗址博物馆", "address": "上城区"}]

    _stub_react(monkeypatch, text="ok", payloads=[{"tool": search_hotels.name, **hotels}])

    out = await nodes_module.booking_node(
        {
            "city": "杭州市",
            "rough_itinerary": "第一天逛西湖",
            "inspiration_list": previous,
            "messages": [HumanMessage(content="帮我订个酒店")],
        }
    )

    assert out["confirmed_attractions"] == previous


async def test_booking_node_declares_missing_data(monkeypatch):
    _stub_react(monkeypatch, text="没搜到。", payloads=[])

    out = await nodes_module.booking_node(
        {"city": "杭州市", "messages": [HumanMessage(content="帮我订个酒店")]}
    )

    assert out["confirmed_hotels"] == []
    assert out.get("error_msg"), "酒店为空必须显式声明"
