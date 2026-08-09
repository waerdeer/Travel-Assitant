"""
=====================================================================
模块名称: base.py
功能描述: 专家技能基类，定义所有 Skill 的标准接口和抽象方法。
=====================================================================
"""

import json
from abc import ABC, abstractmethod
from typing import Optional

from app.agents.base import AgentContext
from app.mcp.client import MCPClient, MCPToolResult
from app.schemas import TripPlan
from app.core.exceptions import TripPlannerError


class BaseSkill(ABC):
    """Skill 是"专业领域方案包"。

    一个 Skill 负责一类专业问题（亲子游 / 穷游 / 美食），
    内部组合 MCP 工具调用 + 专业 prompt，产出针对性方案。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    def keywords(self) -> list[str]:
        """触发该 Skill 的关键词。空列表 = 兜底通用 Skill。"""
        return []

    @property
    def planner_prompt(self) -> str:
        """该领域专用的规划 prompt。可由域-specific 模块覆盖。"""
        return self._build_prompt()

    def __init__(self, mcp: Optional[MCPClient] = None):
        self._mcp: Optional[MCPClient] = mcp
        self._llm = None

    def bind_llm(self, llm) -> None:
        self._llm = llm

    async def _call_tool(self, server: str, tool: str, args: dict) -> MCPToolResult:
        if self._mcp is None:
            return MCPToolResult(success=False, error="未绑定 MCPClient")
        return await self._mcp.call_tool(server, tool, args)

    async def _call_llm(self, prompt: str) -> str:
        if self._llm is None:
            raise TripPlannerError("Skill 未绑定 LLM")
        return await self._llm.chat(prompt)

    def _build_prompt(self) -> str:
        """默认 prompt 模板，Skill 可覆写以加入专业规则。"""
        return f"""你是{self.name}旅行规划专家。

请根据用户行程信息与实时数据，制定一份专业、可执行的旅行计划。

**输出格式:**
必须严格按照以下 JSON 返回:
{{
  "city": "城市名称",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "days": [...],
  "weather_info": [...],
  "overall_suggestions": "总体建议",
  "budget": {{...}}
}}

**要求:**
1. 每天安排 2-3 个景点
2. 包含早中晚三餐
3. weather_info 覆盖每天
4. 温度为纯数字
5. 提供实用而针对性的建议
"""

    async def collect_data(self, context: AgentContext) -> dict:
        """收集规划所需数据：景点 + 天气 + 酒店。各 Skill 可覆写。"""
        attractions = await self._call_tool(
            "amap", "amap_maps_text_search",
            {"keywords": f"{context.preferences} 景点", "city": context.city},
        )
        weather = await self._call_tool(
            "amap", "amap_maps_weather", {"city": context.city},
        )
        hotels = await self._call_tool(
            "amap", "amap_maps_text_search",
            {"keywords": context.accommodation, "city": context.city},
        )
        return {
            "attractions": attractions.content,
            "weather": weather.content,
            "hotels": hotels.content,
        }

    async def execute(self, context: AgentContext) -> TripPlan:
        data = await self.collect_data(context)
        prompt = self.planner_prompt + "\n\n**实时数据:**\n" + json.dumps(data, ensure_ascii=False, indent=2)

        raw = await self._call_llm(prompt)
        plan = TripPlan(**json.loads(_extract_json(raw)))
        plan.city = context.city
        plan.start_date = context.start_date
        plan.end_date = context.end_date
        return plan


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise TripPlannerError("LLM 输出中未找到合法 JSON")
    return text[start : end + 1]