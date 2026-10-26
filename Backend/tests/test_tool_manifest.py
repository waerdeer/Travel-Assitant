"""
工具名漂移守卫 —— 零网络，但永久消灭「工具名写错」这一层 bug。

背景：
    代码曾经调用 amap_maps_weather / amap_maps_text_search，而高德 MCP 服务器
    暴露的名字是 maps_weather / maps_text_search（没有 amap_ 前缀）。服务端返回
    Tool not found，但当时的 MCP 客户端把这个错误吞成了 success=True + 空 content，
    于是四个工具静默返回 "[]"，LLM 幻觉出整份行程单。

    这个测试不访问网络：它拿一份**抓下来的**真实工具清单（fixtures/），
    离线断言代码里声明的工具名确实存在于服务端。
"""

import re
from pathlib import Path

from app.graph.tools import AMAP_REQUIRED_TOOLS, TOOL_TEXT_SEARCH, TOOL_WEATHER
from conftest import FIXTURES_DIR, load_fixture

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# 历史上错用的前缀。服务端所有工具都是 maps_ 开头。
LEGACY_BAD_PREFIX = "amap_maps_"


def _server_tool_names() -> set[str]:
    manifest = load_fixture("amap_tools_list.json")
    return {t["name"] for t in manifest["result"]["tools"]}


def test_declared_tools_exist_on_server():
    """代码里调用的每个工具名都必须在服务端清单里存在。"""
    server_names = _server_tool_names()
    missing = sorted(set(AMAP_REQUIRED_TOOLS) - server_names)
    assert not missing, (
        f"服务端已不存在这些工具: {missing}\n"
        f"服务端实际提供: {sorted(server_names)}\n"
        f"如服务端确实改名了，请跑 scripts/refresh_fixtures.py 刷新夹具后同步修改常量。"
    )


def test_server_tools_all_use_maps_prefix():
    """服务端工具名一律 maps_ 前缀 —— 这条不变量是上面那个 bug 的根源。"""
    server_names = _server_tool_names()
    offenders = sorted(n for n in server_names if not n.startswith("maps_"))
    assert not offenders, f"服务端出现了非 maps_ 前缀的工具: {offenders}"


def test_constants_use_maps_prefix():
    """常量本身也必须是 maps_ 前缀，防止有人手滑改回去。"""
    assert TOOL_WEATHER.startswith("maps_"), TOOL_WEATHER
    assert TOOL_TEXT_SEARCH.startswith("maps_"), TOOL_TEXT_SEARCH


def test_no_legacy_amap_prefix_in_source():
    """全量扫描源码：不允许再出现 amap_maps_ 字面量。

    工具名收口成常量后，调用点已经不可能手滑；这条测试兜住「有人新写一个工具
    时又照着旧代码抄了个 amap_ 前缀」的情况。
    """
    offenders: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # 跳过注释与文档字符串里的历史说明
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for match in re.finditer(r'"([^"]*)"|\'([^\']*)\'', line):
                literal = match.group(1) or match.group(2) or ""
                if LEGACY_BAD_PREFIX in literal:
                    offenders.append(f"{path.relative_to(APP_DIR.parent)}:{lineno}: {literal}")
    assert not offenders, (
        "源码里仍存在 amap_maps_ 前缀的字符串字面量（服务端没有这些工具）：\n  "
        + "\n  ".join(offenders)
    )


def test_fixtures_dir_is_populated():
    """夹具缺失时给出可执行的修复指引，而不是让上面的测试莫名其妙地报错。"""
    expected = {
        "amap_tools_list.json",
        "amap_text_search_ok.json",
        "amap_weather_ok.json",
        "amap_empty_pois.json",
        "amap_tool_not_found.json",
    }
    present = {p.name for p in FIXTURES_DIR.glob("*.json")}
    missing = sorted(expected - present)
    assert not missing, f"缺少夹具 {missing}，请运行: python scripts/refresh_fixtures.py"
