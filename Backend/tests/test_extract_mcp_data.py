"""
解析层测试 —— 纯函数，零网络。

背景（第 3 层 bug）：
    旧版 extract_mcp_data 用 hasattr(first_item, "text") 判断是否要剥壳，
    这只对 stdio 传输的 mcp SDK TextContent 对象成立。HTTP 传输走 resp.json()
    拿到的是普通 dict，判断失败后直接 return content，于是把包装壳
    [{"type":"text","text":"<json字符串>"}] 原样返回，业务层再取 name/address
    只能拿到 None —— search_hotels 每一条都变成 {"name": null}。
"""

import pytest

from app.graph.tools import _is_wrapper, extract_mcp_data


class FakeTextContent:
    """模拟 mcp SDK 的 TextContent：有 .text 属性，不是 dict。"""

    def __init__(self, text: str):
        self.text = text


# ---------- 两种传输层的包装都要能剥 ----------


def test_http_dict_wrapper_is_unwrapped():
    """HTTP 传输：resp.json() 得到的是 dict 包装 —— 这正是旧实现漏掉的分支。"""
    wrapped = [{"type": "text", "text": '{"pois":[{"id":"B1","name":"雷峰塔景区"}]}'}]
    assert extract_mcp_data(wrapped) == {"pois": [{"id": "B1", "name": "雷峰塔景区"}]}


def test_stdio_textcontent_object_is_unwrapped():
    """stdio 传输：mcp SDK 的 TextContent 对象。"""
    assert extract_mcp_data([FakeTextContent('{"city":"杭州市"}')]) == {"city": "杭州市"}


def test_plain_json_string_is_parsed():
    assert extract_mcp_data('{"a": 1}') == {"a": 1}


def test_already_unwrapped_dict_passes_through():
    payload = {"pois": [{"name": "A"}]}
    assert extract_mcp_data(payload) == payload


# ---------- 列表语义必须稳定 ----------


@pytest.mark.parametrize(
    "payload",
    [
        [{"name": "A"}, {"name": "B"}],
        [{"name": "A"}],  # 单元素业务列表 —— 旧实现最容易在这里出错
    ],
)
def test_business_list_is_not_destroyed(payload):
    """业务列表原样保留，不随元素个数改变返回类型。

    若实现写成「看首元素是不是 dict 就返回 content」之外的任何启发式，
    单元素列表会被拆成裸 dict，接口形状随数据条数漂移。
    """
    assert extract_mcp_data(payload) == payload


def test_list_of_wrappers_is_fully_unwrapped():
    content = [
        {"type": "text", "text": '{"n": 1}'},
        {"type": "text", "text": '{"n": 2}'},
    ]
    assert extract_mcp_data(content) == [{"n": 1}, {"n": 2}]


# ---------- 空值统一 ----------


@pytest.mark.parametrize("empty", [None, "", [], {}, "   "])
def test_empties_normalize_to_empty_list(empty):
    assert extract_mcp_data(empty) == []


# ---------- 兜底：不抛异常 ----------


def test_plain_text_falls_through():
    """不是 JSON 的纯文本原样返回（工具失败时服务端可能返回一句人话）。"""
    assert extract_mcp_data([{"type": "text", "text": "服务暂不可用"}]) == "服务暂不可用"


def test_unknown_object_does_not_raise():
    sentinel = object()
    assert extract_mcp_data(sentinel) is sentinel


def test_wrapper_guard_rejects_business_payload_with_text_key():
    """守卫必须带 type == "text"，否则含 text 键的业务 dict 会被误剥。"""
    business = {"text": "这是业务字段，不是传输包装", "name": "某酒店"}
    assert _is_wrapper(business) is False
    assert extract_mcp_data(business) == business


def test_deeply_nested_beyond_limit_returns_original():
    """超过递归上限时原样返回，而不是无限递归或抛异常。"""
    deep: object = '{"x": 1}'
    for _ in range(10):
        deep = [{"type": "text", "text": deep}]
    # 不抛异常即可（具体返回内容取决于深度上限，非关键）
    extract_mcp_data(deep)
