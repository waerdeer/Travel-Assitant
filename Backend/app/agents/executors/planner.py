import json
from app.agents.base import BaseAgent, AgentContext, AgentResult
from app.agents.prompts.planner import PLANNER_AGENT_PROMPT
from app.schemas import TripPlan


class PlannerExecutor(BaseAgent):
    @property
    def name(self) -> str:
        return "行程规划"

    async def execute(self, context: AgentContext) -> AgentResult:
        try:
            prompt = PLANNER_AGENT_PROMPT

            llm_response = await self._call_llm(prompt)
            trip_plan = self._parse_response(llm_response)

            return AgentResult(success=True, data=trip_plan, raw_response=llm_response)
        except Exception as e:
            return AgentResult(success=False, error=str(e))

    async def _call_llm(self, prompt: str) -> str:
        raise NotImplementedError("需接入 LLM 客户端")

    def _parse_response(self, raw: str) -> TripPlan:
        data = json.loads(raw)
        return TripPlan(**data)
