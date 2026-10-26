from typing import TypedDict, List, Dict, Any, Optional, Annotated
from pydantic import BaseModel, Field
import operator
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage

class TripState(TypedDict, total=False):
    """旅行规划 Agent 的全局共享状态 (支持多轮对话记忆)"""
    
    # ====== 核心机制 ======
    # add_messages 会自动将新消息追加到列表末尾，而不是覆盖
    messages: Annotated[list[AnyMessage], add_messages] 
    intent: str                  # 路由中枢识别出的用户意图 (new_trip, modify_hotel, chat)
    
    # ====== 用户需求 ======
    city: str
    start_date: str
    end_date: str
    persona: str
    custom_preferences: str
    
    # ====== 执行过程数据 ======
    weather_context: str
    inspiration_list: List[Dict]
    rough_itinerary: str
    confirmed_hotels: List[Dict]
    confirmed_attractions: List[Dict]
    
    # ====== 最终产出 ======
    final_plan_md: str
    current_step_count: int
    error_msg: Optional[str]
    requirements: dict
    decision: dict
    evidence: List[Dict]
    itinerary: Optional[dict]
    validation: dict
    trace: List[Dict]
    metrics: dict
    status: str
    reply: str
    repair_count: int
    tool_calls: int
    research_round: int
    missing_requirements: List[str]
    previous_itinerary: Optional[dict]
    previous_plan_md: str
    accepted_plan: dict
    interaction_mode: str
    pending_choice: Optional[dict]
    choice_selection: Optional[dict]
    selected_options: dict
    choice_confirmed: bool
    review_categories: List[str]
    scope_policy_version: int
    spatial_repair_no_progress: bool
    planning_strategy: str
    route_draft: Optional[dict]
    requested_review_categories: List[str]
    preferred_options: dict
    run_id: str
