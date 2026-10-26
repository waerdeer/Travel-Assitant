"""
=====================================================================
模块名称: refresh_fixtures.py
功能描述: 从真实高德 MCP 服务器抓取响应，落盘为 tests/fixtures/ 下的测试夹具。

为什么需要它：
    tests/ 里的夹具必须是「抓来的」而不是「编的」。手写的假数据只能验证
    「代码符合我的想象」，抓来的真实响应才能验证「代码符合服务端的行为」——
    本次四层 bug 恰恰是代码与真实契约不符造成的。

用法:
    cd Backend && python scripts/refresh_fixtures.py

副作用:
    会覆盖 tests/fixtures/*.json。夹具变化时请 review diff 再提交。
=====================================================================
"""

import asyncio
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

from app.mcp.registry import mcp_client  # noqa: E402

FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"

AMAP_SERVER = "amap"
TOOL_WEATHER = "maps_weather"
TOOL_TEXT_SEARCH = "maps_text_search"

# 故意用一个「填充词多」的关键词：实测它会把景点(110202)、便利店(060200)
# 混进酒店结果里，正好给 typecode 过滤测试当燃料。
MESSY_HOTEL_KEYWORDS = "西湖景区 附近的 中档 酒店 住宿"


def _write(name: str, payload) -> None:
    path = FIXTURES_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    size = path.stat().st_size
    print(f"  ✓ {name}  ({size} bytes)")


async def _call_ok(tool: str, args: dict) -> dict:
    """调用工具并断言成功，返回 {"result": {"content": [...]}} 形式的信封。"""
    result = await mcp_client.call_tool(AMAP_SERVER, tool, args)
    if not result.success:
        raise RuntimeError(f"{tool} 调用失败: {result.error}")
    return {"result": {"content": result.content, "isError": result.is_error}}


async def _capture_raw_rpc_error(tool: str, args: dict) -> dict:
    """故意调用一个不存在的工具，抓取真实的 JSON-RPC error 信封。

    这个夹具驱动 test_mcp_client_errors.py —— 也就是第 2 层 bug 的回归测试。
    """
    url = mcp_client._resolve_url(mcp_client._servers[AMAP_SERVER].url)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=payload, headers=mcp_client._http_headers())
        return resp.json()


async def main() -> None:
    config_path = BACKEND_DIR / "app" / "mcp" / "servers.json"
    await mcp_client.load_config(str(config_path))
    print("已加载 MCP 配置，开始抓取夹具 ->", FIXTURES_DIR)

    # 1. 工具清单（驱动 test_tool_manifest.py，零网络消灭「工具名写错」）
    tools = await mcp_client.list_tools(AMAP_SERVER)
    _write("amap_tools_list.json", {"result": {"tools": tools}})

    # 2. 天气成功响应
    _write("amap_weather_ok.json", await _call_ok(TOOL_WEATHER, {"city": "杭州市"}))

    # 3. 文本搜索成功响应（含污染项，供 typecode 过滤测试使用）
    _write(
        "amap_text_search_ok.json",
        await _call_ok(
            TOOL_TEXT_SEARCH, {"city": "杭州市", "keywords": MESSY_HOTEL_KEYWORDS}
        ),
    )

    # 4. 空结果响应（验证「调用成功但为空」不被当成失败）
    _write(
        "amap_empty_pois.json",
        await _call_ok(
            TOOL_TEXT_SEARCH,
            {"city": "杭州市", "keywords": "zzz不存在的关键词zzz", "citylimit": True},
        ),
    )

    # 5. 真实的 JSON-RPC 错误信封
    _write(
        "amap_tool_not_found.json",
        await _capture_raw_rpc_error("amap_maps_weather", {"city": "杭州市"}),
    )

    await mcp_client.close()
    print("完成。")


if __name__ == "__main__":
    asyncio.run(main())
