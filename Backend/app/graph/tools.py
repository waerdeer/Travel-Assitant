import json
import logging

logger = logging.getLogger("app.graph.tools")


from typing import Optional, List, Dict, Union, Any, Literal
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from app.services.images import poi_images
from app.core.exceptions import ToolCallError
from app.mcp.client import MCPToolResult
from app.mcp.registry import mcp_client
from app.graph.place_policy import unavailable_place

# ==========================================
# 0. MCP 工具名常量
# ==========================================
# 高德 MCP 服务器暴露的工具名一律是 maps_ 前缀，没有 amap_ 前缀。
# 历史上这里手写了 "amap_maps_weather" / "amap_maps_text_search"，服务端返回
# {"error": {"code": -32603, "message": "Tool not found: ..."}}，而当时的客户端
# 把这个错误吞成了 success=True + 空 content，于是四个工具静默返回 "[]"，
# LLM 拿不到任何真实数据后幻觉出了整份行程单。
#
# 收口成常量后：调用点不会再手滑，且 AMAP_REQUIRED_TOOLS 可被
# scripts/refresh_fixtures.py 抓下来的工具清单离线断言（见 tests/test_tool_manifest.py）。

AMAP_SERVER = "amap"
TOOL_WEATHER = "maps_weather"
TOOL_TEXT_SEARCH = "maps_text_search"
TOOL_DETAIL = "maps_search_detail"
TOOL_AROUND = "maps_around_search"

# 启动校验与测试断言用：这些工具必须在服务端 tools/list 里存在
AMAP_REQUIRED_TOOLS = (TOOL_WEATHER, TOOL_TEXT_SEARCH, TOOL_DETAIL, TOOL_AROUND)

# ==========================================
# 工具 1：天气查询
# ==========================================

_MAX_UNWRAP_DEPTH = 5


def _is_wrapper(item: Any) -> bool:
    """该元素是否还是 MCP 传输层包装（而不是业务载荷）。

    这是重写解析层时引入的关键抽象。旧实现用「元素是对象还是 dict」来区分传输层：
        if hasattr(first_item, "text"):   # 只对 stdio 的 TextContent 成立
    但正确的判断维度是「**元素是不是包装层**」——stdio 的 TextContent 对象和
    HTTP 的 {"type": "text", "text": ...} 是同一种东西的两种表示，旧实现只认前者，
    于是 HTTP 路径把包装壳原样返回，业务层再从中取 name/address 只能拿到 None。

    注意 dict 分支必须带 type == "text" 守卫，否则一个恰好含 "text" 键的
    业务 payload 会被误剥。
    """
    if isinstance(item, str):
        return True  # 可能是待解析的 JSON 字符串
    if hasattr(item, "text"):
        return True  # stdio: mcp SDK 的 TextContent
    if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
        return True  # http: resp.json() 得到的 content block
    return False


def extract_mcp_data(content: Any, _depth: int = 0) -> Any:
    """递归剥掉 MCP 传输层包装，返回业务载荷（dict / list / str）。

    兼容三类来源：
      1. stdio  —— mcp SDK 的 TextContent 对象列表
      2. http   —— resp.json() 得到的 [{"type":"text","text":"<json字符串>"}]
      3. 已解包 —— 纯 dict / list / str

    约定：
      - 永远不抛异常；解不开就原样返回，空值统一成 []。
      - 用 [] 表示「没有载荷」，**不区分「调用失败」和「调用成功但为空」**——
        那个区分由上游 MCPToolResult.success 和业务层的 count 承担。解析层保持纯函数。
    """
    if _depth > _MAX_UNWRAP_DEPTH:
        logger.warning("extract_mcp_data 递归超过 %d 层，原样返回", _MAX_UNWRAP_DEPTH)
        return content

    if content is None or content == "" or content == [] or content == {}:
        return []

    # 1) JSON 字符串 → 解析后继续剥
    if isinstance(content, str):
        stripped = content.strip()
        if not stripped:
            return []
        try:
            return extract_mcp_data(json.loads(stripped), _depth=_depth + 1)
        except (json.JSONDecodeError, ValueError):
            return content  # 纯文本（例如 "服务暂不可用"），原样返回

    # 2) stdio 的 TextContent 对象
    text = getattr(content, "text", None)
    if isinstance(text, str):
        return extract_mcp_data(text, _depth=_depth + 1)

    # 3) 其他 SDK 内容对象（ImageContent / EmbeddedResource 等）
    if hasattr(content, "model_dump") and not isinstance(content, (dict, list)):
        return extract_mcp_data(content.model_dump(), _depth=_depth + 1)

    # 4) 列表：只有「每个元素都还是包装层」时才继续拆
    if isinstance(content, list):
        if not all(_is_wrapper(item) for item in content):
            # 业务列表原样返回。这条守卫保证列表语义不随条数变化：
            # 若写成「看首元素类型」，一个单元素业务列表会被错误拆成 dict，
            # 接口形状就会随数据条数漂移，极难排查。
            return content
        if len(content) == 1:
            return extract_mcp_data(content[0], _depth=_depth + 1)
        unwrapped = [extract_mcp_data(item, _depth=_depth + 1) for item in content]
        return [item for item in unwrapped if item not in ([], None, "")]

    # 5) 字典
    if isinstance(content, dict):
        # 5a. HTTP 传输的 content block —— 本次 bug 的关键分支
        if content.get("type") == "text" and "text" in content:
            return extract_mcp_data(content["text"], _depth=_depth + 1)
        # 5b. JSON-RPC 信封
        if "jsonrpc" in content:
            if "result" in content:
                return extract_mcp_data(content["result"], _depth=_depth + 1)
            return []
        if isinstance(content.get("result"), dict) and "content" in content["result"]:
            return extract_mcp_data(content["result"], _depth=_depth + 1)
        # 5c. 业务载荷，放行
        return content

    return content


# ==========================================
# 1. 业务层：高德返回结构 → 稳定 schema
# ==========================================
# 实测的真实结构（由 scripts/refresh_fixtures.py 抓取确认）：
#   maps_weather     -> {"city": "上海市", "forecasts": [{date, dayweather, daytemp, ...}]}
#   maps_text_search -> {"suggestion": {...}, "pois": [{id, name, address, typecode, photo}]}
#
# POI 只有 id/name/address/typecode/photo 五个字段 —— 没有经纬度、没有评分、没有价格。
# search_hotels 的 docstring 曾写「含名称、地址、经纬度等」，那是在骗 LLM，
# 会让它因为「数据不完整」而反复重试。

# 高德 POI 分类码：**前 2 位是大类**，例如
#   10 住宿服务  -> 100000 住宿服务 / 100100 宾馆酒店 / 100105 经济型连锁酒店
#   05 餐饮服务  -> 050000 餐饮服务 / 050100 中餐厅 / 050700 咖啡茶饮
#   11 风景名胜  -> 110200 风景名胜 / 110202 西湖风景名胜区
#   20 公共设施  -> 200300 公共厕所 ！  15 交通设施 -> 150904 停车场 ！
#
# 注意不要用 4 位前缀："100100" 并不以 "1000" 开头（它以 "1001" 开头），
# 用 4 位会把所有酒店全部过滤掉。用 2 位大类码才是正确的层级。
#
# 另外实测 typecode 可能是竖线多值，例如酒店 "100105|061100"、餐厅 "050700|050600"，
# 必须 split("|") 后逐个比。
TC_HOTEL = ("10",)  # 住宿服务大类
TC_RESTAURANT = ("05",)  # 餐饮服务大类

# 天气字段白名单：砍掉 daytemp_float 等冗余字段，让返回形状确定、可控
_WEATHER_KEEP = (
    "date",
    "week",
    "dayweather",
    "nightweather",
    "daytemp",
    "nighttemp",
    "daywind",
    "nightwind",
    "daypower",
    "nightpower",
)


def _match_typecode(typecode: str, prefixes: Optional[tuple]) -> bool:
    """typecode 前缀匹配。prefixes 为 None 时全部放行。"""
    if not prefixes:
        return True
    codes = str(typecode).split("|")
    return any(code.startswith(prefix) for code in codes for prefix in prefixes)


def _normalize_poi(raw: dict) -> Optional[dict]:
    """把高德 POI 归一化成给 LLM 的最小 schema。名称缺失的条目直接丢弃。

    这里是**唯一的字段收口点**：将来若要补经纬度/评分，只改这一处，
    不必去翻四个工具。id 保留下来作为未来做 maps_search_detail / maps_around_search
    富化时的关联键。
    """
    name = str(raw.get("name") or "").strip()
    if not name or unavailable_place(raw):
        return None  # 无名条目对 LLM 是纯噪声
    item = {
        "name": name,
        "address": str(raw.get("address") or "").strip(),
        "typecode": str(raw.get("typecode") or ""),
        "id": str(raw.get("id") or ""),
    }
    images = poi_images(raw)
    if images:
        item["image_urls"] = images
    if isinstance(raw.get("cityname"), str):
        item["cityname"] = raw["cityname"]
    if isinstance(raw.get("location"), str) and raw["location"]:
        item["location"] = raw["location"]
    for key in ("business_status", "operating_status", "status"):
        if isinstance(raw.get(key), str):
            item[key] = raw[key]
    return item


def _extract_pois(
    pure_data: Any,
    limit: int,
    *,
    typecode_prefixes: Optional[tuple] = None,
) -> tuple:
    """从 maps_text_search 的返回里取 pois 并归一化。

    返回 (items, notice)。notice 非空时说明结果经过裁剪或过滤，需要告知 LLM。
    """
    if isinstance(pure_data, list):
        candidates = pure_data
    elif isinstance(pure_data, dict):
        candidates = [pure_data]
    else:
        return [], ""

    raws: List[dict] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        pois = candidate.get("pois")
        if pois is None and isinstance(candidate.get("data"), dict):
            pois = candidate["data"].get("pois")
        if isinstance(pois, list):
            raws.extend(p for p in pois if isinstance(p, dict))

    all_items = [item for item in (_normalize_poi(p) for p in raws) if item]
    if not all_items:
        return [], ""

    filtered = [i for i in all_items if _match_typecode(i["typecode"], typecode_prefixes)]
    notice = ""
    if typecode_prefixes and not filtered:
        notice = f"按类型过滤后无匹配（{len(all_items)} 条结果的类型均不符）。不得将其他类型当作所需地点。"
    elif typecode_prefixes and len(filtered) < len(all_items):
        notice = f"已从 {len(all_items)} 条结果中筛出 {len(filtered)} 条类型匹配的条目。"

    return filtered[:limit], notice


def _extract_weather(pure_data: Any) -> dict:
    """maps_weather → {"city": str, "forecasts": [...]}"""
    if isinstance(pure_data, list):
        pure_data = next((d for d in pure_data if isinstance(d, dict)), {})
    if not isinstance(pure_data, dict):
        return {}
    forecasts = pure_data.get("forecasts")
    if not isinstance(forecasts, list):
        return {}
    return {
        "city": str(pure_data.get("city") or ""),
        "forecasts": [
            {k: f.get(k, "") for k in _WEATHER_KEEP} for f in forecasts if isinstance(f, dict)
        ],
    }


# ==========================================
# 2. 给 LLM 的统一返回契约
# ==========================================
# 三态，用 ok 字段区分：
#   成功有数据  {"ok": true,  "count": N, "items": [...]}
#   成功但为空  {"ok": true,  "count": 0, "items": [], "notice": "..."}
#   失败        {"ok": false, "error": {"code","retryable","tool","message","hint"}}
#
# 事故根因就是 LLM 收到裸 "[]" 时无法区分「工具坏了」和「真的没结果」，
# 于是按 prompt 的「搜不到就换关键词重试」理解，无限重试直到撞 limit。
# ok 让「要不要重试」变成单 token 的判断。

_NON_RETRYABLE_HINT = {
    "tool_not_found": "服务端不存在该工具（配置问题）。禁止重试，请用你的常识继续，并在最终回复中注明该部分未使用实时数据。",
    "invalid_params": "参数不合法。修正参数后最多重试一次。",
    "protocol_error": "服务端返回了非预期响应。禁止重试，请用常识继续并在最终回复中注明。",
    "tool_error": "工具执行了但业务失败。可调整关键词后重试一次。",
    "config_error": "本地 MCP 配置错误。禁止重试，请用常识继续并在最终回复中注明。",
}

_RETRYABLE_HINT = (
    "这是临时性故障。更换关键词或参数后最多重试一次；再次失败请停止调用该工具，基于已有信息作答。"
)


def _ok_payload(items: List[dict], *, notice: str = "", **extra) -> str:
    payload = {"ok": True, "count": len(items), "items": items, **extra}
    if not items:
        payload["notice"] = notice or (
            "调用成功，但没有匹配结果。最多再换一次关键词；仍为空请停止调用该工具。"
        )
    elif notice:
        payload["notice"] = notice
    return json.dumps(payload, ensure_ascii=False)


def _error_payload(tool: str, result: MCPToolResult) -> str:
    code = result.error_code or "unknown"
    retryable = bool(result.retryable)
    hint = (
        _RETRYABLE_HINT
        if retryable
        else _NON_RETRYABLE_HINT.get(code, "禁止重试，请用常识继续并在最终回复中注明。")
    )
    logger.error(
        "工具失败 tool=%s code=%s retryable=%s err=%s",
        tool,
        code,
        retryable,
        result.error,
    )
    return json.dumps(
        {
            "ok": False,
            "error": {
                "code": code,
                "retryable": retryable,
                "tool": tool,
                "message": (result.error or "")[:300],
                "hint": hint,
            },
        },
        ensure_ascii=False,
    )


async def _call_mcp(tool_name: str, args: dict) -> tuple:
    """调用 MCP，返回 (MCPToolResult | None, 错误信封 | None)。

    只捕获 ToolCallError（本地配置类错误）。其余异常让它冒到 LangChain ——
    框架会把它变成带错误信息的 ToolMessage，信息量比我们自己吞掉更大。
    旧实现在四个工具里各写了一个宽泛 except Exception，那是第 2 层 bug
    的最后一道掩护，也是 ToolCallError 全项目没人接的原因。
    """
    try:
        return await mcp_client.call_tool(AMAP_SERVER, tool_name, args), None
    except ToolCallError as e:
        logger.error("MCP 配置错误 tool=%s: %s", tool_name, e, exc_info=True)
        return None, _error_payload(
            tool_name,
            MCPToolResult(success=False, error=str(e), error_code="config_error", retryable=False),
        )


# ==========================================
# 工具 1：天气查询
# ==========================================
class WeatherInput(BaseModel):
    city: str = Field(
        ...,
        description="标准的城市名称，必须包含后缀，例如 '北京市', '杭州市', '成都市'。不能使用简写。",
    )


@tool("get_weather_and_climate", args_schema=WeatherInput)
async def get_weather_and_climate(city: str) -> str:
    """
    【核心工具】查询目的地的天气和气候信息。
    触发时机：当你需要知道目的地的气温、降雨概率以决定是否安排户外活动，或给出穿衣建议时调用。
    期望返回：JSON。成功形如 {"ok": true, "count": N, "city": "杭州市", "items": [{date, dayweather, daytemp, nighttemp, ...}]}；
             失败形如 {"ok": false, "error": {"code", "retryable", "hint"}}。
    """
    result, error = await _call_mcp(TOOL_WEATHER, {"city": city})
    if error:
        return error
    if not result.success:
        return _error_payload(TOOL_WEATHER, result)

    weather = _extract_weather(extract_mcp_data(result.content))
    if not weather:
        return _ok_payload([], notice=f"调用成功，但未从响应中解析出 {city} 的天气数据。")
    return _ok_payload(weather["forecasts"], city=weather["city"])


# ==========================================
# 工具 2：景点灵感搜索
# ==========================================
class InspirationInput(BaseModel):
    city: str = Field(..., description="城市名称，如 '上海市'")
    keywords: str = Field(
        ..., description="搜索关键词或偏好，例如 '亲子游乐园', '历史遗迹', '必去景点', '博物馆'"
    )
    max_results: int = Field(default=5, description="希望获取的最大结果数量，建议保持默认 5")


@tool("search_travel_inspiration", args_schema=InspirationInput)
async def search_travel_inspiration(city: str, keywords: str, max_results: int = 5) -> str:
    """
    【核心工具】根据给定的关键词，在指定城市搜索旅游景点、灵感或特色活动。
    触发时机：当你需要了解某个城市有什么好玩的地方，或者根据用户的特定偏好（如"亲子"、"博物馆"、"自然风光"）寻找游玩地时使用。
    使用建议：keyword 请用具体的游玩主题（如 '博物馆'、'历史遗迹'、'亲子乐园'），不要用 '景点' 这种泛词。
    期望返回：JSON。成功形如 {"ok": true, "count": N, "items": [{"name", "address", "typecode", "id"}]}。
    """
    result, error = await _call_mcp(
        TOOL_TEXT_SEARCH, {"city": city, "keywords": keywords, "citylimit": True}
    )
    if error:
        return error
    if not result.success:
        return _error_payload(TOOL_TEXT_SEARCH, result)

    # 刻意不做 typecode 过滤：本工具的 prompt 要求支持「博物馆 / 亲子游乐园 /
    # 历史遗迹」，而博物馆在 140000（科教文化服务）不在 110000（风景名胜）。
    # 硬套景点前缀会把用户明确要的博物馆全部丢掉 —— 过度过滤等于制造新的空结果。
    items, notice = _extract_pois(
        extract_mcp_data(result.content), limit=max_results, typecode_prefixes=None
    )
    return _ok_payload(items, notice=notice)


# ==========================================
# 工具 3：酒店住宿搜索
# ==========================================
class HotelSearchInput(BaseModel):
    city: str = Field(..., description="城市名称，如 '杭州市'")
    poi_location: str = Field(
        ...,
        description="期望居住的地标、景区或核心商圈，如 '西湖景区', '武林广场'。必须明确具体地点。",
    )
    budget_level: str = Field(
        default="中档", description="预算偏好，仅限输入：'经济型', '中档', '豪华', '民宿'"
    )


@tool("search_hotels", args_schema=HotelSearchInput)
async def search_hotels(city: str, poi_location: str, budget_level: str = "中档") -> str:
    """
    【核心工具】在指定城市的特定地标附近搜索酒店住宿。
    触发时机：当你进入预订节点，需要根据行程草案中的主要游玩区域来寻找落脚点时调用。
    使用约束：
    1. 你必须先明确用户要游玩的核心区域，将该区域填入 `poi_location`。
    2. 本工具只返回住宿类结果（已按 POI 类型过滤），返回空说明该地标附近确实没有。
    期望返回：JSON。成功形如 {"ok": true, "count": N, "items": [{"name", "address", "typecode", "id"}]}。
             注意 items 里没有价格和评分字段 —— 高德搜索接口不提供，请勿据此编造价格。
    """
    # 实测：去掉 "附近的 / 住宿" 这类填充词后住宿类命中率不降，噪声更少。
    # 用旧关键词 "西湖景区 附近的 中档 酒店 住宿" 时，20 条结果里混进了
    # 景点(110202)、便利店(060200)、公共厕所(200300)、停车场(150904)。
    style = {"经济型": "经济型连锁酒店", "豪华": "豪华酒店", "民宿": "民宿"}.get(
        budget_level, "酒店"
    )
    keywords = f"{poi_location} {style}" if poi_location else f"{city} {style}"
    result, error = await _call_mcp(
        TOOL_TEXT_SEARCH, {"city": city, "keywords": keywords, "citylimit": True}
    )
    if error:
        return error
    if not result.success:
        return _error_payload(TOOL_TEXT_SEARCH, result)

    # typecode 过滤在这里不是优化而是必需项：不过滤就会把公共厕所当成酒店喂给 LLM。
    items, notice = _extract_pois(
        extract_mcp_data(result.content), limit=20, typecode_prefixes=TC_HOTEL
    )
    # Search direction is not proof of lodging type: real economic-hotel
    # searches around West Lake returned only homestays. Separate explicit
    # name signals before truncation; an empty group can broaden once in research.
    items = lodging_direction(items, budget_level)
    if not items:
        notice = "没有匹配该住宿方向的名称证据，可有限扩大区域检索；不能把其他类型冒充该类住宿。"
    return _ok_payload(items[:5], notice=notice)


# ==========================================
# 工具 4：餐厅美食搜索
# ==========================================
class RestaurantSearchInput(BaseModel):
    city: str = Field(..., description="城市名称")
    poi_location: str = Field(
        ..., description="当前游玩的地标或酒店名称，如 '迪士尼乐园', '如家酒店'"
    )
    food_type: str = Field(
        default="特色美食", description="餐饮偏好，如 '当地特色', '亲子餐厅', '不辣的菜'"
    )


@tool("search_restaurants", args_schema=RestaurantSearchInput)
async def search_restaurants(city: str, poi_location: str, food_type: str = "特色美食") -> str:
    """
    【核心工具】根据所在位置搜索附近的餐厅或美食。
    触发时机：当你需要为每天的行程补充午餐或晚餐安排时调用。
    期望返回：JSON。成功形如 {"ok": true, "count": N, "items": [{"name", "address", "typecode", "id"}]}。
             只返回餐饮类结果，没有价格字段。
    """
    term = (
        food_type
        if any(word in food_type for word in ("小吃", "面馆", "早餐", "咖啡", "茶馆"))
        else f"{food_type} 餐厅"
    )
    keywords = f"{poi_location or city} {term}"
    result, error = await _call_mcp(
        TOOL_TEXT_SEARCH, {"city": city, "keywords": keywords, "citylimit": True}
    )
    if error:
        return error
    if not result.success:
        return _error_payload(TOOL_TEXT_SEARCH, result)

    items, notice = _extract_pois(
        extract_mcp_data(result.content), limit=6, typecode_prefixes=TC_RESTAURANT
    )
    return _ok_payload(items, notice=notice)


def lodging_direction(items: list[dict], profile: str) -> list[dict]:
    """Name signals only; this is not a price or star-rating classifier."""
    words = ("民宿", "客栈", "农家乐", "旅舍")
    return [
        item for item in items if any(word in item["name"] for word in words) == (profile == "民宿")
    ]


class NearbyInput(BaseModel):
    city: str
    location: str = Field(pattern=r"^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$")
    category: Literal["hotel", "restaurant"]
    keywords: str = ""
    hotel_profile: Literal["经济型", "中档", "豪华", "民宿"] | None = None


@tool("search_nearby_pois", args_schema=NearbyInput)
async def search_nearby_pois(
    city: str, location: str, category: str, keywords: str = "", hotel_profile: str | None = None
) -> str:
    """在已确认景点坐标 5 km 内检索住宿或餐厅，修复市级搜索的跨区噪声。"""
    term = "酒店" if category == "hotel" else "餐厅"
    if category == "hotel" and hotel_profile:
        term = {"经济型": "经济型连锁酒店", "豪华": "豪华酒店", "民宿": "民宿"}.get(
            hotel_profile, "酒店"
        )
        keywords = ""
    result, error = await _call_mcp(
        TOOL_AROUND,
        {"location": location, "keywords": f"{keywords} {term}".strip(), "radius": "5000"},
    )
    if error:
        return error
    if not result.success:
        return _error_payload(TOOL_AROUND, result)
    items, notice = _extract_pois(
        extract_mcp_data(result.content),
        limit=20 if hotel_profile and category == "hotel" else 5,
        typecode_prefixes=TC_HOTEL if category == "hotel" else TC_RESTAURANT,
    )
    if category == "hotel" and hotel_profile:
        items = lodging_direction(items, hotel_profile)
        if not items:
            notice = (
                "周边没有匹配该住宿方向的名称证据，不能把民宿冒充酒店或把检索方向当作星级认证。"
            )
    return _ok_payload(items[:5], notice=notice)


# 导出供 Sub-Agent 绑定
INFO_TOOLS = [get_weather_and_climate, search_travel_inspiration]
BOOKING_TOOLS = [search_hotels]
PLANNER_TOOLS = [search_restaurants]


class NamedPlaceInput(BaseModel):
    city: str
    name: str = Field(min_length=1, max_length=120)
    category: Literal["hotel", "restaurant"]


@tool("search_named_place", args_schema=NamedPlaceInput)
async def search_named_place(city: str, name: str, category: str) -> str:
    """定位用户明确指定的酒店或餐厅，不用泛化搜索替代该地点。"""
    result, error = await _call_mcp(
        TOOL_TEXT_SEARCH, {"city": city, "keywords": name, "citylimit": True}
    )
    if error:
        return error
    if not result.success:
        return _error_payload(TOOL_TEXT_SEARCH, result)
    items, notice = _extract_pois(
        extract_mcp_data(result.content),
        limit=5,
        typecode_prefixes=TC_HOTEL if category == "hotel" else TC_RESTAURANT,
    )
    return _ok_payload(items, notice=notice)
