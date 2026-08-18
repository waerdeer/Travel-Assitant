from typing import Dict, Any, List
import json
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from pydantic import BaseModel, Field
from langgraph.prebuilt import create_react_agent

from app.core.config import settings
from app.graph.state import TripState
from app.graph.tools import (
    INFO_TOOLS,
    BOOKING_TOOLS,
    PLANNER_TOOLS
)

llm = ChatOpenAI(
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
    model=settings.llm_model,
    temperature=0.7
)

# ==========================================
# 0. 路由中枢节点 (Router Node) -> 纯 LLM 节点，不变
# ==========================================
class RouterOutput(BaseModel):
    intent: str = Field(description="用户意图分类，仅限以下三种：'new_trip'(全新行程规划), 'modify_hotel'(修改酒店住宿), 'chat'(普通问答或闲聊)")
    city: str = Field(default="", description="若是全新行程，提取城市")
    start_date: str = Field(default="", description="提取开始日期，例如 2026-08-18")
    end_date: str = Field(default="", description="提取结束日期，例如 2026-08-19")
    custom_preferences: str = Field(default="", description="提取游玩或住宿的特殊要求")

async def router_node(state: TripState) -> Dict[str, Any]:
    """意图识别中枢：分析最新的用户输入，决定走向"""
    today = datetime.now().strftime("%Y-%m-%d")
    sys_prompt = f"""
    你是一个旅行助理的路由大脑。今天是 {today}。
    请根据用户最新发送的消息，以及之前的聊天记录，判断他的意图：
    1. 如果用户要求规划一个全新的行程，或者更换了城市，分类为 'new_trip'，并提取 city, date 等。
    2. 如果用户是在现有的行程基础上，要求更换酒店/住宿，分类为 'modify_hotel'。
    3. 如果用户只是在问候、致谢，或者问一些无关旅行规划的普通问题，分类为 'chat'。
    
    之前确定的城市是: {state.get('city', '无')}。
    """
    structured_llm = llm.with_structured_output(RouterOutput)
    messages = [SystemMessage(content=sys_prompt)] + state["messages"]
    
    try:
        # Fallback due to API not supporting structured outputs directly
        # Let's prompt it to output raw JSON if structured_llm fails
        res = await structured_llm.ainvoke(messages)
        intent = res.intent
        city = res.city
        start_date = res.start_date
        end_date = res.end_date
        pref = res.custom_preferences
    except Exception as e:
        # Fallback prompt for strict JSON if with_structured_output failed
        fallback_msg = messages + [HumanMessage(content="请务必只输出包含 intent, city, start_date, end_date, custom_preferences 的标准 JSON 字符串，不要带任何其他前缀后缀。")]
        fallback_res = await llm.ainvoke(fallback_msg)
        try:
            content = fallback_res.content
            if content.startswith("```json"): content = content[7:-3]
            parsed = json.loads(content)
            intent = parsed.get("intent", "new_trip")
            city = parsed.get("city", "未知")
            start_date = parsed.get("start_date", "")
            end_date = parsed.get("end_date", "")
            pref = parsed.get("custom_preferences", "")
        except Exception:
            intent = "chat"; city = ""; start_date = ""; end_date = ""; pref = ""

    update_data = {"intent": intent}
    if intent == "new_trip" and city:
        update_data.update({
            "city": city,
            "start_date": start_date or today,
            "end_date": end_date or today,
            "custom_preferences": pref,
            "persona": "通用标准"
        })
    return update_data

# ==========================================
# 0.5 普通闲聊节点 (Chat Node) -> 纯 LLM 节点，不变
# ==========================================
async def chat_node(state: TripState) -> Dict[str, Any]:
    sys_prompt = "你是一个友好的旅行助理，请简短、礼貌地回复用户的闲聊或问题。"
    messages = [SystemMessage(content=sys_prompt)] + state["messages"]
    res = await llm.ainvoke(messages)
    return {
        "messages": [AIMessage(content=res.content)],
        "final_plan_md": res.content
    }

# ==========================================
# 1. 收集情报节点 (Info Agent - ReAct 架构)
# ==========================================
class InfoOutput(BaseModel):
    weather_context: str = Field(description="总结的天气情况与穿衣/出行建议")
    inspiration_list: List[Dict[str, Any]] = Field(description="收集到的候选景点列表，包含 name 和 address 等")

async def info_agent(state: TripState) -> Dict[str, Any]:
    """收集情报：利用 ReAct 代理自主收集足够的情报"""
    city = state.get("city", "未知城市")
    
    # 1. 定义 ReAct 代理的系统指令
    agent_sys_prompt = (
        f"你是一个不达目的不罢休的情报分析师。任务：为去【{city}】的游客收集情报。\n"
        f"游客偏好：{state.get('custom_preferences', '')}。\n"
        f"指令：\n"
        f"1. 必须调用天气工具查询近期天气。\n"
        f"2. 必须调用景点灵感工具搜索适合的景点。如果第一次搜索结果不理想，请自主更换关键词重新搜索，直到收集到至少 4 个以上的优质景点。\n"
        f"3. 完成上述收集后，请直接输出一段总结性的文字，包含所有查到的天气和景点信息。"
    )
    
    # 2. 创建独立运转的 ReAct 子代理
    react_agent = create_react_agent(llm, tools=INFO_TOOLS, prompt=agent_sys_prompt)
    
    # 3. 驱动子代理运行
    invoke_input = {"messages": [HumanMessage(content="请开始利用工具收集情报。")]}
    # 限制递归步数，防止陷入死循环导致账单爆炸
    config = {"recursion_limit": 5}
    
    try:
        agent_res = await react_agent.ainvoke(invoke_input, config)
        # 获取代理得出的最终推理论文
        final_answer = agent_res["messages"][-1].content
    except Exception as e:
        # 如果超出步数报错，兜底处理
        final_answer = f"情报搜集部分失败，请基于已知常识推断。错误: {str(e)}"

    # 4. State Out：出参规约 (让 LLM 将大白话提炼回 TripState 严格格式)
    extractor_llm = llm.with_structured_output(InfoOutput)
    try:
        parsed = await extractor_llm.ainvoke([
            SystemMessage(content="请从以下文字中提取天气和景点列表。"),
            HumanMessage(content=final_answer)
        ])
        weather_context = parsed.weather_context
        inspiration_list = parsed.inspiration_list
    except Exception:
        weather_context = final_answer
        inspiration_list = [{"name": "热门景点推荐"}]
        
    return {
        "weather_context": weather_context,
        "inspiration_list": inspiration_list
    }

# ==========================================
# 2. 生成草案节点 (Draft Node) -> 纯推理节点
# ==========================================
async def draft_node(state: TripState) -> Dict[str, Any]:
    sys_prompt = (
        f"请制定一个每日游玩大纲草案。\n"
        f"城市: {state.get('city')} \n天气: {state.get('weather_context')}\n"
        f"候选景点: {json.dumps(state.get('inspiration_list', []), ensure_ascii=False)}"
    )
    res = await llm.ainvoke([
        SystemMessage(content=sys_prompt),
        HumanMessage(content="请直接输出包含每天大纲的文字版行程草案。")
    ])
    return {"rough_itinerary": res.content}

# ==========================================
# 3. 订机票酒店节点 (Booking Node - ReAct 架构)
# ==========================================
class BookingOutput(BaseModel):
    confirmed_hotels: List[Dict[str, Any]] = Field(description="最终确定的酒店列表")
    confirmed_attractions: List[Dict[str, Any]] = Field(description="最终确定的景点列表")

async def booking_node(state: TripState) -> Dict[str, Any]:
    city = state.get("city", "未知城市")
    
    agent_sys_prompt = (
        f"你是一个严谨的后勤预订管家。任务：在【{city}】为用户寻找合适的住宿酒店。\n"
        f"草案/修改要求: {state.get('rough_itinerary')}\n"
        f"用户最新消息: {state['messages'][-1].content}\n"
        f"偏好要求: {state.get('custom_preferences')}\n"
        f"指令：\n"
        f"1. 你必须严格按照行程草案中的地标，调用搜索酒店工具。\n"
        f"2. 如果发现目标区域没有符合预算的酒店，请自主扩大搜索半径或改变地标关键词重新搜索。\n"
        f"3. 找到合适的酒店后，输出一段总结文本，列出你选定的酒店和景点安排。"
    )
    
    react_agent = create_react_agent(llm, tools=BOOKING_TOOLS, prompt=agent_sys_prompt)
    invoke_input = {"messages": [HumanMessage(content="请帮我寻找酒店。")]}
    
    try:
        agent_res = await react_agent.ainvoke(invoke_input, {"recursion_limit": 5})
        final_answer = agent_res["messages"][-1].content
    except Exception as e:
        final_answer = f"搜索酒店部分失败。错误: {str(e)}"

    extractor_llm = llm.with_structured_output(BookingOutput)
    try:
        parsed = await extractor_llm.ainvoke([
            SystemMessage(content="请从以下总结中提取最终确认的酒店和景点列表。"),
            HumanMessage(content=final_answer)
        ])
        confirmed_hotels = parsed.confirmed_hotels
        confirmed_attractions = parsed.confirmed_attractions
    except Exception:
        confirmed_hotels = []
        confirmed_attractions = []
        
    return {
        "confirmed_hotels": confirmed_hotels,
        "confirmed_attractions": confirmed_attractions
    }

# ==========================================
# 4. 排最终行程节点 (Planner Node - ReAct 架构)
# ==========================================
async def planner_node(state: TripState) -> Dict[str, Any]:
    city = state.get('city')
    
    agent_sys_prompt = (
        f"你是一个精益求精的旅行编辑，也是交付给用户的最后一关。\n"
        f"你现在掌握以下信息：\n"
        f"城市: {city}\n"
        f"天气: {state.get('weather_context')}\n"
        f"确认酒店: {json.dumps(state.get('confirmed_hotels', []), ensure_ascii=False)}\n"
        f"行程大纲: {state.get('rough_itinerary')}\n"
        f"指令：\n"
        f"1. 审视这几天的行程，自主调用餐厅搜索工具，为游玩地标附近补充午餐和晚餐推荐。如果搜不到，换个宽泛的餐饮词再搜一次。\n"
        f"2. 补充完毕后，请综合所有信息，直接生成一篇精美、专业、格式清晰的 Markdown 行程单作为你的最后一条回复。"
    )
    
    react_agent = create_react_agent(llm, tools=PLANNER_TOOLS, prompt=agent_sys_prompt)
    invoke_input = {"messages": [HumanMessage(content="请开始查漏补缺（搜餐厅），最后交付给我一份完美的 Markdown 行程单。")]}
    
    try:
        agent_res = await react_agent.ainvoke(invoke_input, {"recursion_limit": 5})
        final_markdown = agent_res["messages"][-1].content
    except Exception as e:
        final_markdown = f"生成方案时出错: {str(e)}\n\n请您稍后再试。"
    
    # 记录助手的最终回复到全局上下文，以便多轮对话可见
    return {
        "messages": [AIMessage(content=final_markdown)],
        "final_plan_md": final_markdown
    }
