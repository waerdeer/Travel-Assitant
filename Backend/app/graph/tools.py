import json
import logging
logger = logging.getLogger('app.graph.tools')


from typing import Optional, List, Dict, Union, Any
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from app.mcp.registry import mcp_client

# ==========================================
# 工具 1：天气查询
# ==========================================

def extract_mcp_data(content: Union[List[Any], Dict[str, Any], str, Any]) -> Any:
    """通用解包器：剥离 MCP 的 TextContent 包装，返回纯 Python 字典或列表。"""
    if not content:
        return []
    
    # 场景1: MCP 返回的是对象列表 (例如 TextContent)
    if isinstance(content, list) and len(content) > 0:
        first_item = content[0]
        # MCP python sdk 的 TextContent 对象有 text 属性
        if hasattr(first_item, "text"):
            try:
                return json.loads(first_item.text)
            except Exception:
                return first_item.text
        # 如果列表里直接是 dict，直接返回
        if isinstance(first_item, dict):
            return content

    # 场景2: MCP 返回的是纯 JSON 字符串
    if isinstance(content, str):
        try:
            return json.loads(content)
        except Exception:
            return content

    # 场景3: 已经是字典或列表，直接放行
    return content

class WeatherInput(BaseModel):
    city: str = Field(..., description="标准的城市名称，必须包含后缀，例如 '北京市', '杭州市', '成都市'。不能使用简写。")

@tool("get_weather_and_climate", args_schema=WeatherInput)
async def get_weather_and_climate(city: str) -> str:
    """
    【核心工具】查询目的地的天气和气候信息。
    触发时机：当你需要知道目的地的气温、降雨概率以决定是否安排户外活动，或给出穿衣建议时调用。
    期望返回：将返回该城市未来几天的天气预报 JSON 数据，请提取并总结给用户。
    """
    try:
        result = await mcp_client.call_tool("amap", "amap_maps_weather", {"city": city})
        if result.success:
            pure_data = extract_mcp_data(result.content)
            return json.dumps(pure_data, ensure_ascii=False)
        return f"获取 {city} 天气失败: {result.error}"
    except Exception as e:
        return f"工具调用异常: {str(e)}。请尝试使用其他信息推断。"

# ==========================================
# 工具 2：景点灵感搜索
# ==========================================
class InspirationInput(BaseModel):
    city: str = Field(..., description="城市名称，如 '上海市'")
    keywords: str = Field(..., description="搜索关键词或偏好，例如 '亲子游乐园', '历史遗迹', '必去景点', '博物馆'")
    max_results: int = Field(default=5, description="希望获取的最大结果数量，建议保持默认 5")

@tool("search_travel_inspiration", args_schema=InspirationInput)
async def search_travel_inspiration(city: str, keywords: str, max_results: int = 5) -> str:
    """
    【核心工具】根据给定的关键词，在指定城市搜索旅游景点、灵感或特色活动。
    触发时机：当你需要了解某个城市有什么好玩的地方，或者根据用户的特定偏好（如“亲子”、“博物馆”、“自然风光”）寻找游玩地时使用。
    使用建议：如果第一次搜索结果不理想，请尝试更换 `keywords` (例如从 '景点' 换成 '网红打卡地') 再次搜索。
    期望返回：将返回包含景点名称、地址等信息的列表。
    """
    try:
        arguments = {"city": city, "keywords": keywords}
        result = await mcp_client.call_tool("amap", "amap_maps_text_search", arguments)
        
        if result.success:
            pure_data = extract_mcp_data(result.content)
            items = pure_data if isinstance(pure_data, list) else [pure_data]
            return json.dumps(items[:max_results], ensure_ascii=False)
        return f"搜索景点失败: {result.error}。请尝试缩短或更换 keywords 重新搜索。"
    except Exception as e:
        return f"工具调用异常: {str(e)}。"

# ==========================================
# 工具 3：酒店住宿搜索
# ==========================================
class HotelSearchInput(BaseModel):
    city: str = Field(..., description="城市名称，如 '杭州市'")
    poi_location: str = Field(..., description="期望居住的地标、景区或核心商圈，如 '西湖景区', '武林广场'。必须明确具体地点。")
    budget_level: str = Field(default="中档", description="预算偏好，仅限输入：'经济型', '中档', '豪华', '民宿'")

@tool("search_hotels", args_schema=HotelSearchInput)
async def search_hotels(city: str, poi_location: str, budget_level: str = "中档") -> str:
    """
    【核心工具】在指定城市的特定地标附近搜索酒店住宿。
    触发时机：当你进入预订节点，需要根据行程草案中的主要游玩区域来寻找落脚点时调用。
    使用约束：
    1. 你必须先明确用户要游玩的核心区域，将该区域填入 `poi_location`。
    2. 如果找不到匹配的酒店，尝试把 `budget_level` 改为 '酒店' 进行宽泛搜索。
    期望返回：返回前 5 个最匹配的酒店列表（含名称、地址、经纬度等）。
    """
    try:
        keywords = f"{budget_level} 酒店 住宿"
        if poi_location:
             keywords = f"{poi_location} 附近的 {keywords}"
             
        arguments = {"city": city, "keywords": keywords}
        result = await mcp_client.call_tool("amap", "amap_maps_text_search", arguments)
        
        if result.success:
            pure_data = extract_mcp_data(result.content)
            items = pure_data if isinstance(pure_data, list) else [pure_data]
            simplified = [{"name": item.get("name"), "address": item.get("address"), "type": item.get("type")} for item in items[:5] if isinstance(item, dict)]
            return json.dumps(simplified, ensure_ascii=False)
        return f"搜索酒店失败: {result.error}。请更换 poi_location (如改用地标名称) 重新搜索。"
    except Exception as e:
        return f"工具调用异常: {str(e)}。"

# ==========================================
# 工具 4：餐厅美食搜索
# ==========================================
class RestaurantSearchInput(BaseModel):
    city: str = Field(..., description="城市名称")
    poi_location: str = Field(..., description="当前游玩的地标或酒店名称，如 '迪士尼乐园', '如家酒店'")
    food_type: str = Field(default="特色美食", description="餐饮偏好，如 '当地特色', '亲子餐厅', '不辣的菜'")

@tool("search_restaurants", args_schema=RestaurantSearchInput)
async def search_restaurants(city: str, poi_location: str, food_type: str = "特色美食") -> str:
    """
    【核心工具】根据所在位置搜索附近的餐厅或美食。
    触发时机：当你需要为每天的行程补充午餐或晚餐安排时调用。
    期望返回：返回附近最合适的 3 家餐厅。
    """
    try:
        keywords = f"{poi_location} 附近的 {food_type} 餐厅"
        arguments = {"city": city, "keywords": keywords}
        result = await mcp_client.call_tool("amap", "amap_maps_text_search", arguments)
        
        if result.success:
            pure_data = extract_mcp_data(result.content)
            items = pure_data if isinstance(pure_data, list) else [pure_data]
            simplified = [{"name": i.get("name"), "address": i.get("address")} for i in items[:3] if isinstance(i, dict)]
            return json.dumps(simplified, ensure_ascii=False)
        return f"搜索餐厅失败: {result.error}。请放宽 food_type 重新搜索。"
    except Exception as e:
        return f"工具调用异常: {str(e)}。"

# 导出供 Sub-Agent 绑定
INFO_TOOLS = [get_weather_and_climate, search_travel_inspiration]
BOOKING_TOOLS = [search_hotels]
PLANNER_TOOLS = [search_restaurants]
