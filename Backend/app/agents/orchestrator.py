from langchain_core.messages import HumanMessage
from app.graph.workflow import app_graph

class TripOrchestrator:
    """带记忆与条件路由的 LangGraph 编排器"""

    def __init__(self):
        self.graph = app_graph

    async def plan_trip(self, thread_id: str, text: str) -> dict:
        
        # 只传入用户的最新消息，LangGraph 的 add_messages 机制会自动处理追加
        # (Router Node 内部会根据消息判断，看是否需要覆盖 state 里的 city 等字段)
        update_state = {
            "messages": [HumanMessage(content=text)]
        }

        # 核心：将 thread_id 传给图，让它从内存里拉取上一次执行的快照
        config = {"configurable": {"thread_id": thread_id}}
        
        # 让 LangGraph 图跑起来
        final_state = await self.graph.ainvoke(update_state, config)

        plan_content = final_state.get("final_plan_md", "")
        intent_used = final_state.get("intent", "未知意图")

        return {
            "city": final_state.get("city"),
            "persona": final_state.get("persona"),
            "intent": intent_used,
            "plan_content": plan_content
        }
