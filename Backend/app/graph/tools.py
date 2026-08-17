import json
from typing import Optional
from langchain_core.tools import tool
from app.mcp.registry import mcp_client

@tool
async def get_weather_and_climate(city: str) -> str:
    """
    查询目的地的天气和气候信息。
    在收集情报阶段，必须调用此工具以获取目的地的近期天气状况，以便规划户外活动。
    
    Args:
        city: 目的地城市名称，如 "北京市", "成都市"
    """
    # 这里通过底层的 MCP Client 调用高德天气工具
    # MCP 的 amap_maps_weather 通常需要 city 字段
    result = await mcp_client.call_tool("amap", "amap_maps_weather", {"city": city})
    if result.success:
        return json.dumps(result.content, ensure_ascii=False)
    return f"获取 {city} 天气失败: {result.error}"

@tool
async def search_travel_inspiration(city: str, keywords: str, max_results: int = 5) -> str:
    """
    根据给定的关键词，在指定城市搜索旅游景点、灵感或特色活动。
    当你需要了解某个城市有什么好玩的地方，或者根据用户的特定偏好（如“亲子”、“博物馆”、“自然风光”）寻找游玩地时使用。
    
    Args:
        city: 城市名称，如 "上海市"
        keywords: 搜索关键词或偏好，例如 "亲子游乐园", "历史遗迹", "必去景点"
        max_results: 希望获取的最大结果数量
    """
    # 包装为高德 MCP 文本搜索。高德搜索的 types 可以为空，依赖 keywords 即可。
    arguments = {
        "city": city,
        "keywords": keywords,
        # 可以根据实际底层支持度调整
    }
    result = await mcp_client.call_tool("amap", "amap_maps_text_search", arguments)
    
    if result.success:
        # 可以对庞大的 MCP 返回体进行清洗，防止撑爆 LLM 上下文
        items = result.content if isinstance(result.content, list) else [result.content]
        # 简单取前 N 个
        cleaned_items = items[:max_results]
        return json.dumps(cleaned_items, ensure_ascii=False)
    return f"搜索景点失败: {result.error}"

@tool
async def verify_attraction_detail(name: str, city: str) -> str:
    """
    查询某个特定景点的详细信息，例如开放时间、是否适合儿童、是否需要门票等。
    当草案中初步选定了一个景点，但需要验证其具体情况（尤其是亲子游等特殊需求）时调用此工具。
    
    Args:
        name: 景点名称，如 "故宫博物院"
        city: 景点所在城市，如 "北京市"
    """
    arguments = {
        "city": city,
        "keywords": name,
    }
    # MCP 底层可能需要用 search_detail 或者依旧是 text_search，这里映射到 text_search 进行精确查找
    result = await mcp_client.call_tool("amap", "amap_maps_text_search", arguments)
    
    if result.success:
        # 仅返回最匹配的第一个结果作为详情
        items = result.content if isinstance(result.content, list) else [result.content]
        return json.dumps(items[0] if items else {}, ensure_ascii=False)
    return f"获取详情失败: {result.error}"

@tool
async def search_hotels(city: str, poi_location: str, budget_level: str = "中档") -> str:
    """
    在指定城市的特定地标附近搜索酒店住宿。
    当进入物流/预订节点时，根据行程草案中的主要游玩区域来寻找落脚点。
    
    Args:
        city: 城市名称，如 "杭州市"
        poi_location: 期望居住的地标或区域，如 "西湖景区", "武林广场", "地铁站附近"
        budget_level: 预算偏好，如 "经济型", "中档", "豪华"
    """
    keywords = f"{budget_level} 酒店 住宿"
    if poi_location:
         keywords = f"{poi_location} 附近的 {keywords}"
         
    arguments = {
        "city": city,
        "keywords": keywords,
        # types: "140000" (高德 POI 酒店分类码，可选)
    }
    result = await mcp_client.call_tool("amap", "amap_maps_text_search", arguments)
    
    if result.success:
        items = result.content if isinstance(result.content, list) else [result.content]
        return json.dumps(items[:5], ensure_ascii=False) # 返回前5个
    return f"搜索酒店失败: {result.error}"

@tool
async def search_restaurants(city: str, poi_location: str, food_type: str = "特色美食") -> str:
    """
    根据所在位置搜索附近的餐厅或美食。
    排最终行程时，用来为每天的行程补充午餐或晚餐安排。
    
    Args:
        city: 城市名称
        poi_location: 当前游玩的地标或酒店名称，如 "迪士尼乐园", "如家酒店"
        food_type: 餐饮偏好，如 "当地特色", "亲子餐厅", "不辣的菜"
    """
    keywords = f"{poi_location} 附近的 {food_type} 餐厅"
         
    arguments = {
        "city": city,
        "keywords": keywords,
        # types: "050000" (高德 POI 餐饮分类码)
    }
    result = await mcp_client.call_tool("amap", "amap_maps_text_search", arguments)
    
    if result.success:
        items = result.content if isinstance(result.content, list) else [result.content]
        return json.dumps(items[:3], ensure_ascii=False) # 返回前3个
    return f"搜索餐厅失败: {result.error}"

# 定义一个工具列表，方便后续在 Node 中一次性引入和绑定
ALL_TRIP_TOOLS = [
    get_weather_and_climate,
    search_travel_inspiration,
    verify_attraction_detail,
    search_hotels,
    search_restaurants
]
