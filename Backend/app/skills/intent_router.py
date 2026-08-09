"""
=====================================================================
模块名称: intent_router.py
功能描述: 意图路由模块，负责分析用户输入，并分配给对应的专业领域 Skill 进行处理。
=====================================================================
"""

from app.agents.base import AgentContext
from app.skills.registry import skill_registry


class IntentRouter:
    """意图识别器：把用户输入映射到专业 Skill。

    流程: AgentContext.preferences / accommodation
        → SkillRegistry.resolve() → 返回 BaseSkill 实例
    """

    def __init__(self, registry=None):
        self._registry = registry or skill_registry

    def route(self, context: AgentContext):
        return self._registry.resolve(context)


router = IntentRouter()

__all__ = [
    "IntentRouter",
    "router",
]