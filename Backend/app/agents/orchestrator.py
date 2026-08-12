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

    async def extract_params(self, text: str) -> dict:
        import json
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        
        prompt = f"""
你是一个旅行参数提取器。今天是 {today}。
请从用户的自然语言输入中，提取出旅行计划所需的核心参数，严格以 JSON 格式返回，不要有任何多余字符。
如果用户没有明确说明时间，请默认设定为未来的合理日期（例如下周一出发，玩3天）。如果不明确城市，请你帮助他选择一个符合他期望的城市。
输出格式严格如下：
{{
  "city": "目的地城市名",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "preferences": "提取用户的游玩偏好",
  "accommodation": "提取住宿偏好"
}}

用户输入：{text}
"""
        response_obj = await llm_client.chat(prompt=prompt)
        cleaned = response_obj.content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        
        try:
            return json.loads(cleaned.strip())
        except Exception as e:
            return {
                "city": "京都",
                "start_date": today,
                "end_date": today,
                "preferences": text,
                "accommodation": ""
            }
