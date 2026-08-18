from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.graph.state import TripState
from app.graph.nodes import (
    router_node, 
    chat_node, 
    info_agent, 
    draft_node, 
    booking_node, 
    planner_node
)

def route_after_router(state: TripState) -> str:
    """条件路由函数：根据 Router 节点判断的 intent 决定下一个节点"""
    intent = state.get("intent", "chat")
    if intent == "new_trip":
        return "收集情报"
    elif intent == "modify_hotel":
        return "订机票酒店"
    else:
        return "普通闲聊"

def build_workflow() -> StateGraph:
    workflow = StateGraph(TripState)
    
    # 注册所有节点
    workflow.add_node("路由中枢", router_node)
    workflow.add_node("普通闲聊", chat_node)
    
    workflow.add_node("收集情报", info_agent)
    workflow.add_node("生成草案", draft_node)
    workflow.add_node("订机票酒店", booking_node)
    workflow.add_node("排最终行程", planner_node)
    
    # 建立边
    workflow.add_edge(START, "路由中枢")
    
    # 核心：条件路由边
    workflow.add_conditional_edges(
        "路由中枢", 
        route_after_router,
        {
            "收集情报": "收集情报",
            "订机票酒店": "订机票酒店",
            "普通闲聊": "普通闲聊"
        }
    )
    
    # 闲聊结束
    workflow.add_edge("普通闲聊", END)
    
    # 全新行程的主干道
    workflow.add_edge("收集情报", "生成草案")
    workflow.add_edge("生成草案", "订机票酒店")
    
    # 无论是顺流而下，还是从条件路由直接跳过来，最终都走排版
    workflow.add_edge("订机票酒店", "排最终行程")
    workflow.add_edge("排最终行程", END)
    
    return workflow

# 引入内存持久化
memory = MemorySaver()

# 编译图时挂载 Checkpointer
app_graph = build_workflow().compile(checkpointer=memory)
