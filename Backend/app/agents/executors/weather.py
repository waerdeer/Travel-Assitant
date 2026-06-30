from app.agents.base import BaseAgent, AgentContext, AgentResult
from app.agents.prompts.weather import WEATHER_AGENT_PROMPT
from app.tools.amap import AmapClient
from app.schemas import WeatherInfo


class WeatherExecutor(BaseAgent):
    @property
    def name(self) -> str:
        return "天气查询"

    async def execute(self, context: AgentContext) -> AgentResult:
        try:
            prompt = WEATHER_AGENT_PROMPT.format(city=context.city)

            llm_response = await self._call_llm(prompt)
            tool_call = self._parse_tool_call(llm_response)
            raw_data = await AmapClient.weather_query(city=tool_call.params["city"])
            weather_list = [WeatherInfo(**item) for item in raw_data]

            return AgentResult(success=True, data=weather_list, raw_response=llm_response)
        except Exception as e:
            return AgentResult(success=False, error=str(e))

    async def _call_llm(self, prompt: str) -> str:
        raise NotImplementedError("需接入 LLM 客户端")

    def _parse_tool_call(self, response: str) -> "ToolCall":
        from app.tools.amap import ToolCall
        return ToolCall.parse(response)
