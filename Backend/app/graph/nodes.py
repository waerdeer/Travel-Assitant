from typing import Dict, Any, List
import json

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from app.core.config import settings
from app.graph.state import TripState
from app.graph.tools import (
    get_weather_and_climate, 
    search_travel_inspiration, 
    search_hotels, 
    search_restaurants
)

# 统一初始化 LLM (使用 langchain_openai 适配 LangGraph)
llm = ChatOpenAI(
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
    model=settings.llm_model,
    temperature=0.7
)

# ==========================================
# 1. 收集情报节点 (Info Agent)
# ==========================================
class InfoOutput(BaseModel):
    weather_context: str = Field(description="总结的天气情况与穿衣/出行建议")
    inspiration_list: List[Dict[str, Any]] = Field(description="收集到的候选景点和活动列表")

async def info_agent(state: TripState) -> Dict[str, Any]:
    """收集情报：调用天气和景点灵感工具"""
    tools = [get_weather_and_climate, search_travel_inspiration]
    llm_with_tools = llm.bind_tools(tools)
    
    city = state.get("city", "未知城市")
    sys_prompt = (
        f"你是一个专业的旅行情报收集员。任务：为去【{city}】的游客收集情报。\n"
        f"游客画像与偏好：{state.get('persona', '')}，{state.get('custom_preferences', '')}。\n"
        f"请先调用天气工具，然后再调用景点灵感工具搜索适合他们的景点。"
    )
    messages = [SystemMessage(content=sys_prompt), HumanMessage(content="开始收集情报吧。")]
    
    # 第1次调用：触发工具
    ai_msg = await llm_with_tools.ainvoke(messages)
    messages.append(ai_msg)
    
    # 执行工具
    if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls:
        for call in ai_msg.tool_calls:
            tool_fn = next((t for t in tools if t.name == call["name"]), None)
            if tool_fn:
                res = await tool_fn.ainvoke(call["args"])
                messages.append(ToolMessage(content=str(res), tool_call_id=call["id"]))
    
    # 第2次调用：结构化总结输出
    structured_llm = llm.with_structured_output(InfoOutput)
    messages.append(HumanMessage(content="请根据工具返回的结果，总结天气情况，并提取灵感景点列表。"))
    final_res = await structured_llm.ainvoke(messages)
    
    return {
        "weather_context": final_res.weather_context,
        "inspiration_list": final_res.inspiration_list,
        "current_step_count": state.get("current_step_count", 0) + 1
    }

# ==========================================
# 2. 生成草案节点 (Draft Node)
# ==========================================
async def draft_node(state: TripState) -> Dict[str, Any]:
    """生成草案：纯 LLM 推理节点，不调工具"""
    sys_prompt = (
        f"你是一个资深旅行架构师。请根据以下情报，为用户制定一个每日游玩大纲草案（不用太详细，定好每天去哪个区域/核心景点即可）。\n"
        f"城市: {state.get('city')}\n"
        f"日期: {state.get('start_date')} 到 {state.get('end_date')}\n"
        f"用户偏好: {state.get('persona')} {state.get('custom_preferences')}\n"
        f"天气情报: {state.get('weather_context')}\n"
        f"候选景点: {json.dumps(state.get('inspiration_list', []), ensure_ascii=False)}\n"
    )
    
    res = await llm.ainvoke([
        SystemMessage(content=sys_prompt),
        HumanMessage(content="请直接输出包含每天大纲的文字版行程草案。")
    ])
    
    return {
        "rough_itinerary": res.content,
        "current_step_count": state.get("current_step_count", 0) + 1
    }

# ==========================================
# 3. 订机票酒店节点 (Booking Node)
# ==========================================
class BookingOutput(BaseModel):
    confirmed_hotels: List[Dict[str, Any]] = Field(description="最终确定的酒店列表")
    confirmed_attractions: List[Dict[str, Any]] = Field(description="最终确定的景点列表")

async def booking_node(state: TripState) -> Dict[str, Any]:
    """预订节点：根据草案搜索具体酒店"""
    tools = [search_hotels]
    llm_with_tools = llm.bind_tools(tools)
    
    sys_prompt = (
        f"你是一个后勤管家。请根据以下行程草案，为用户寻找合适的住宿酒店。\n"
        f"城市: {state.get('city')}\n"
        f"用户偏好: {state.get('persona')} {state.get('custom_preferences')}\n"
        f"行程草案: {state.get('rough_itinerary')}\n"
        f"请调用 search_hotels 工具，在草案中提到的核心区域附近寻找酒店。"
    )
    messages = [SystemMessage(content=sys_prompt), HumanMessage(content="请帮我寻找酒店。")]
    
    ai_msg = await llm_with_tools.ainvoke(messages)
    messages.append(ai_msg)
    
    if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls:
        for call in ai_msg.tool_calls:
            if call["name"] == "search_hotels":
                res = await search_hotels.ainvoke(call["args"])
                messages.append(ToolMessage(content=str(res), tool_call_id=call["id"]))
                
    structured_llm = llm.with_structured_output(BookingOutput)
    messages.append(HumanMessage(content="请总结最终确认的酒店列表，以及草案中确定要去的景点列表。"))
    final_res = await structured_llm.ainvoke(messages)
    
    return {
        "confirmed_hotels": final_res.confirmed_hotels,
        "confirmed_attractions": final_res.confirmed_attractions,
        "current_step_count": state.get("current_step_count", 0) + 1
    }

# ==========================================
# 4. 排最终行程节点 (Planner Node)
# ==========================================
async def planner_node(state: TripState) -> Dict[str, Any]:
    """最终行程节点：可以搜索餐厅，并排版最终 Markdown"""
    tools = [search_restaurants]
    llm_with_tools = llm.bind_tools(tools)
    
    sys_prompt = (
        f"你是一个旅行排版编辑，负责出具最终的旅行方案。\n"
        f"你需要将以下信息整合成一份精美的 Markdown 行程单：\n"
        f"城市: {state.get('city')} ({state.get('start_date')} ~ {state.get('end_date')})\n"
        f"天气提醒: {state.get('weather_context')}\n"
        f"确认酒店: {json.dumps(state.get('confirmed_hotels', []), ensure_ascii=False)}\n"
        f"行程大纲: {state.get('rough_itinerary')}\n"
        f"你可以调用 search_restaurants 工具为游玩区域补充一些餐厅推荐。"
    )
    
    messages = [SystemMessage(content=sys_prompt), HumanMessage(content="请先搜下餐厅，然后生成最终 Markdown 方案。")]
    
    ai_msg = await llm_with_tools.ainvoke(messages)
    messages.append(ai_msg)
    
    if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls:
        for call in ai_msg.tool_calls:
            if call["name"] == "search_restaurants":
                res = await search_restaurants.ainvoke(call["args"])
                messages.append(ToolMessage(content=str(res), tool_call_id=call["id"]))
                
    messages.append(HumanMessage(content="请综合所有信息，直接输出最终的精美 Markdown 行程单（不要带 ```markdown 语法，直接输出文本）。"))
    final_res = await llm.ainvoke(messages)
    
    return {
        "final_plan_md": final_res.content,
        "current_step_count": state.get("current_step_count", 0) + 1
    }
