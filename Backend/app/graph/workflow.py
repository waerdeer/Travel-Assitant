from langgraph.graph import StateGraph, START, END

from app.graph.state import TripState
from app.graph.nodes import info_agent, draft_node, booking_node, planner_node

def build_workflow() -> StateGraph:
    """构建并返回旅行规划的工作流图。"""
    
    # 1. 初始化图，绑定状态结构
    workflow = StateGraph(TripState)
    
    # 2. 注册所有节点
    workflow.add_node("收集情报", info_agent)
    workflow.add_node("生成草案", draft_node)
    workflow.add_node("订机票酒店", booking_node)
    workflow.add_node("排最终行程", planner_node)
    
    # 3. 定义图的边（拓扑结构）
    # 目前按照严格串行的流程流转
    workflow.add_edge(START, "收集情报")
    workflow.add_edge("收集情报", "生成草案")
    workflow.add_edge("生成草案", "订机票酒店")
    workflow.add_edge("订机票酒店", "排最终行程")
    workflow.add_edge("排最终行程", END)
    
    return workflow

# 暴露出编译后的图实例供上层（Orchestrator 或 API）直接调用
app_graph = build_workflow().compile()
