"""
=====================================================================
模块名称: general.py
功能描述: 专家技能：常规游，处理普通的、没有特殊偏好的旅行请求。
=====================================================================
"""

from app.skills.base import BaseSkill


class GeneralTripSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "通用行程"

    @property
    def description(self) -> str:
        return "通用旅行规划，覆盖大多数行程需求"

    @property
    def keywords(self) -> list[str]:
        return []