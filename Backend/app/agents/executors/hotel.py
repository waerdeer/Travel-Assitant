from app.agents.base import BaseAgent, AgentContext, AgentResult
from app.agents.prompts.hotel import HOTEL_AGENT_PROMPT
from app.tools.amap import AmapClient
from app.schemas import Hotel


class HotelExecutor(BaseAgent):
    @property
    def name(self) -> str:
        return "酒店推荐"

    async def execute(self, context: AgentContext) -> AgentResult:
        try:
            prompt = HOTEL_AGENT_PROMPT.format(
                city=context.city,
                accommodation=context.accommodation,
            )

            llm_response = await self._call_llm(prompt)
            tool_call = self._parse_tool_call(llm_response)
            raw_data = await AmapClient.text_search(**tool_call.params)
            hotels = [Hotel(**item) for item in raw_data]

            return AgentResult(success=True, data=hotels, raw_response=llm_response)
        except Exception as e:
            return AgentResult(success=False, error=str(e))

    async def _call_llm(self, prompt: str) -> str:
        raise NotImplementedError("需接入 LLM 客户端")

    def _parse_tool_call(self, response: str) -> "ToolCall":
        from app.tools.amap import ToolCall
        return ToolCall.parse(response)
