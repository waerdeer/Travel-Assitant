from app.skills.dag import DAGContext
from app.skills.executor import DAGExecutor
from app.skills.registry import skill_registry
from app.mcp.registry import mcp_client
from app.core.llm import llm_client


class TripOrchestrator:
    """编排器：匹配 DAG → 执行 DAG → 返回方案。"""

    def __init__(self):
        self.registry = skill_registry
        self.executor = DAGExecutor(mcp_client, llm_client)

    async def plan_trip(
        self,
        city: str,
        start_date: str,
        end_date: str,
        preferences: str = "",
        accommodation: str = "",
    ) -> dict:
        context = DAGContext(
            city=city,
            start_date=start_date,
            end_date=end_date,
            preferences=preferences,
            accommodation=accommodation,
        )

        dag = self.registry.resolve(context)
        results = await self.executor.run(dag, context)

        plan_data = results.get("generate_plan")
        if plan_data is None:
            raise RuntimeError("行程生成失败：最终步骤未返回数据")

        return {
            "city": city,
            "start_date": start_date,
            "end_date": end_date,
            "preferences": preferences,
            "plan_content": plan_data,
            "steps": list(results.keys()),
        }
