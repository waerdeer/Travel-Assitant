"""
业务层归一化测试 —— 纯函数，零网络。

背景（第 4 层 bug）：
    maps_text_search 的真实结构是 {"suggestion": {...}, "pois": [...]}，
    POI 列表在 pois 键下。旧实现直接对包装 dict 做 items[:5]，
    产出 [{"name": null, "address": null, "type": "text"}]。
"""

import pytest

from app.graph.tools import (
    TC_HOTEL,
    TC_RESTAURANT,
    _extract_pois,
    _extract_weather,
    _match_typecode,
    _normalize_poi,
)
from conftest import load_fixture


def _pois_from_fixture(name: str) -> list:
    """从抓下来的夹具里取出原始 POI 列表。"""
    import json

    envelope = load_fixture(name)
    return json.loads(envelope["result"]["content"][0]["text"]).get("pois", [])


# ---------- typecode 匹配 ----------


@pytest.mark.parametrize(
    "typecode,prefixes,expected",
    [
        ("100100", TC_HOTEL, True),
        ("100000", TC_HOTEL, True),
        ("200300", TC_HOTEL, False),  # 公共厕所
        ("150904", TC_HOTEL, False),  # 停车场
        ("100105|061100", TC_HOTEL, True),  # 竖线多值，任一段命中即可
        ("050700|050600", TC_RESTAURANT, True),
        ("100100", None, True),  # 不过滤时全部放行
        ("", TC_HOTEL, False),
    ],
)
def test_match_typecode(typecode, prefixes, expected):
    assert _match_typecode(typecode, prefixes) is expected


# ---------- POI 归一化 ----------


def test_normalize_poi_keeps_stable_schema():
    raw = {
        "id": "B0GDJR3Z0Z",
        "name": "海友酒店(上海外滩延安东路店)",
        "address": "上海工商联大厦3楼",
        "typecode": "100100",
        "photo": "https://example.com/x.jpg",
    }
    assert _normalize_poi(raw) == {
        "name": "海友酒店(上海外滩延安东路店)",
        "address": "上海工商联大厦3楼",
        "typecode": "100100",
        "id": "B0GDJR3Z0Z",
        "image_urls": ["https://example.com/x.jpg"],
    }


@pytest.mark.parametrize("raw", [{"name": ""}, {"name": "   "}, {"id": "x"}, {}])
def test_normalize_poi_drops_nameless_entries(raw):
    """无名条目对 LLM 是纯噪声，直接丢弃。"""
    assert _normalize_poi(raw) is None


# ---------- 从真实夹具里取 pois ----------


def test_extract_pois_reads_the_pois_key():
    """核心回归：必须从 pois 键取，而不是把包装 dict 当结果。"""
    envelope = load_fixture("amap_text_search_ok.json")
    import json

    pure = json.loads(envelope["result"]["content"][0]["text"])

    items, _ = _extract_pois(pure, limit=100, typecode_prefixes=None)
    assert len(items) == 20
    # 旧实现每条都是 {"name": None, "address": None, "type": "text"}
    assert all(item["name"] for item in items)
    assert all(item["id"] for item in items)


def test_extract_pois_filters_out_non_lodging():
    """这份夹具里 20 条只有 11 条是住宿类，其余是景点/便利店/公厕/停车场。"""
    envelope = load_fixture("amap_text_search_ok.json")
    import json

    pure = json.loads(envelope["result"]["content"][0]["text"])

    items, notice = _extract_pois(pure, limit=100, typecode_prefixes=TC_HOTEL)
    assert items, "过滤后不该为空"
    # 从常量派生断言，避免常量改了测试还在验证旧前缀
    assert all(_match_typecode(i["typecode"], TC_HOTEL) for i in items)
    assert len(items) < 20, "确实过滤掉了东西"
    assert notice, "被裁剪时必须告知 LLM"

    # 确认被剔除的是哪些：公厕、停车场、便利店、景点
    kept = {i["typecode"] for i in items}
    dropped = {
        p["typecode"]
        for p in _pois_from_fixture("amap_text_search_ok.json")
        if p.get("typecode") not in kept
    }
    assert any(tc.startswith(("2003", "1509")) for tc in dropped), (
        f"公厕/停车场应被剔除，实际剔除的是 {sorted(dropped)}"
    )
    # 反向守卫：住宿类一条都不许被误杀
    assert not any(tc.startswith("10") for tc in dropped), (
        f"住宿类被误杀: {sorted(tc for tc in dropped if tc.startswith('10'))}"
    )


def test_extract_pois_never_treats_other_categories_as_hotels():
    """类型不符就是无匹配；重试次数由执行器强制限制。"""
    pure = {"pois": [{"id": "1", "name": "某景点", "typecode": "110202"}]}
    items, notice = _extract_pois(pure, limit=5, typecode_prefixes=TC_HOTEL)
    assert items == [], "不能把景点冒充酒店交给规划器"
    assert "类型均不符" in notice


def test_extract_pois_on_empty_pois_returns_empty_without_notice():
    envelope = load_fixture("amap_empty_pois.json")
    import json

    pure = json.loads(envelope["result"]["content"][0]["text"])
    items, notice = _extract_pois(pure, limit=5, typecode_prefixes=TC_HOTEL)
    assert items == []
    assert notice == ""  # 空结果的 notice 由 _ok_payload 统一生成


def test_extract_pois_respects_limit():
    envelope = load_fixture("amap_text_search_ok.json")
    import json

    pure = json.loads(envelope["result"]["content"][0]["text"])
    items, _ = _extract_pois(pure, limit=3, typecode_prefixes=None)
    assert len(items) == 3


@pytest.mark.parametrize("garbage", [None, "", [], 123, "纯文本"])
def test_extract_pois_never_raises(garbage):
    assert _extract_pois(garbage, limit=5) == ([], "")


# ---------- 天气 ----------


def test_extract_weather_from_real_fixture():
    envelope = load_fixture("amap_weather_ok.json")
    import json

    pure = json.loads(envelope["result"]["content"][0]["text"])
    weather = _extract_weather(pure)

    assert weather["city"] == "杭州市"
    assert weather["forecasts"], "必须有预报数据"
    first = weather["forecasts"][0]
    assert first["date"] and first["dayweather"]
    # 白名单之外的冗余字段应被剔除，保证返回形状稳定
    assert "daytemp_float" not in first


@pytest.mark.parametrize("garbage", [None, [], {}, "纯文本", {"city": "杭州市"}])
def test_extract_weather_never_raises(garbage):
    assert isinstance(_extract_weather(garbage), dict)
