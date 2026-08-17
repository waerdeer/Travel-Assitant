from typing import TypedDict, List, Dict, Any, Optional
from pydantic import BaseModel, Field

class TripState(TypedDict):
    """
    旅行规划 Agent 的全局共享状态。
    所有 Node 均会读取此状态，并对相应字段进行追加或覆盖。
    """
    # ====== 1. 用户初始需求 (输入层) ======
    original_input: str          # 用户最原始的自然语言输入
    city: str                    # 目的地城市
    start_date: str              # 计划开始日期
    end_date: str                # 计划结束日期
    persona: str                 # 自动推导的用户画像/风格 (如 family, budget, foodie, standard)
    custom_preferences: str      # 其他具体诉求 (如 "不吃辣", "要求住得好一点")
    
    # ====== 2. 情报收集阶段 (Info Agent 产出) ======
    weather_context: str         # 获取到的天气、气温和相关穿衣/出行建议
    inspiration_list: List[Dict] # 初步收集的可能去的景点/活动候选池
    
    # ====== 3. 规划草案阶段 (Draft Node 产出) ======
    rough_itinerary: str         # LLM 构思的文字版每日粗略大纲 (例如：Day1 上午A，下午B)
    
    # ====== 4. 物流预订阶段 (Booking Node 产出) ======
    confirmed_hotels: List[Dict] # 落地的酒店信息
    confirmed_attractions: List[Dict] # 最终筛选确认的景点信息
    
    # ====== 5. 最终生成阶段 (Planner Node 产出) ======
    final_plan_md: str           # 交付给用户的最终 Markdown 精美行程方案
    
    # ====== 6. 流程控制与容错 ======
    current_step_count: int      # 记录当前已流转步数，防止 ReAct 无限循环
    error_msg: Optional[str]     # 记录中间节点的报错信息，用于触发重试路由
