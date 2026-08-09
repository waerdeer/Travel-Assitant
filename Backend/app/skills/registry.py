"""
=====================================================================
模块名称: registry.py
功能描述: 技能注册表，管理和索引所有可用的专家技能（Skills）。
=====================================================================
"""

from app.agents.base import AgentContext
from app.skills.base import BaseSkill
from app.skills.general import GeneralTripSkill
from app.skills.family import FamilyTripSkill
from app.skills.budget import BudgetTripSkill
from app.skills.food import FoodTripSkill


class SkillRegistry:
    """Skill 注册中心：管理所有可用 Skill，并按意图路由。"""

    def __init__(self):
        self._skills: list[BaseSkill] = [
            GeneralTripSkill(),
            FamilyTripSkill(),
            BudgetTripSkill(),
            FoodTripSkill(),
        ]

    def register(self, skill: BaseSkill) -> None:
        self._skills.append(skill)

    def all(self) -> list[BaseSkill]:
        return list(self._skills)

    def resolve(self, context: AgentContext) -> BaseSkill:
        """根据用户偏好/描述，匹配最合适的 Skill。

        匹配规则（按注册顺序）：
        1. 领域 Skill 的关键词命中优先
        2. 都没命中 → 兜底用 GeneralTripSkill
        """
        text = f"{context.preferences} {context.accommodation}"
        for skill in self._skills:
            if skill.keywords and any(k in text for k in skill.keywords):
                return skill
        return self._skills[0]


skill_registry = SkillRegistry()

__all__ = [
    "SkillRegistry",
    "skill_registry",
]