"""
=====================================================================
模块名称: orchestrator.py
功能描述: 核心编排器（中央大脑），负责意图识别、工作流调度及多 Agent 协同分发。
=====================================================================
"""

import os

from app.agents.base import AgentContext
from app.core.llm import llm_client
from app.mcp.registry import mcp_client
from app.skills.intent_router import IntentRouter
from app.schemas import TripPlan


class TripOrchestrator:
    """编排器：意图识别 → 匹配 Skill → MCP 取数据 → LLM 生成方案。

    调用入口:
        orchestrator = TripOrchestrator()
        plan = await orchestrator.plan_trip(
            city="北京", start_date="2026-07-01",
            end_date="2026-07-03", preferences="亲子",
        )
    """

    def __init__(self):
        self.router = IntentRouter()
        self.mcp = mcp_client
        self.llm = llm_client

    async def plan_trip(
        self,
        city: str,
        start_date: str,
        end_date: str,
        preferences: str = "",
        accommodation: str = "",
    ) -> TripPlan:
        context = AgentContext(
            city=city,
            start_date=start_date,
            end_date=end_date,
            preferences=preferences,
            accommodation=accommodation,
        )

        servers_path = os.path.join(
            os.path.dirname(__file__), "..", "mcp", "servers.json"
        )
        await self.mcp.load_config(servers_path)

        # 1. 意图识别 → 选择专业 Skill
        skill = self.router.route(context)

        # 2. 给 Skill 绑定运行时依赖
        skill.bind_llm(self.llm)
        skill._mcp = self.mcp

        # 3. 执行 Skill（内部 MCP 取数据 + 专业 prompt + LLM）
        return await skill.execute(context)