"""
=====================================================================
模块名称: family.py
功能描述: 专家技能：亲子游，包含带小孩家庭出游的特定处理逻辑（如游乐场、轻松行程）。
=====================================================================
"""

from app.skills.base import BaseSkill


class FamilyTripSkill(BaseSkill):
    """亲子游专家：考虑安全、设施、节奏与儿童需求。"""

    @property
    def name(self) -> str:
        return "亲子游"

    @property
    def description(self) -> str:
        return "适合带娃出行的行程规划，关注安全、轻松节奏与亲子设施"

    @property
    def keywords(self) -> list[str]:
        return ["亲子", "带娃", "孩子", "小朋友", "儿童", "家庭"]

    @property
    def planner_prompt(self) -> str:
        return """你是亲子游旅行规划专家。

**专业规则（必须遵守）:**
1. 每天景点不超过 2 个，预留充足午休与机动时间
2. 优先选择对儿童友好、安全性高的景点（动物园、博物馆、主题乐园等）
3. 关注闭园时间与高峰时段，避开排队久的热门景点
4. 餐饮推荐为孩子友好的餐厅，注明是否适合儿童
5. 酒店推荐近景点、近医疗资源、有亲子设施的
6. 总体建议要包含儿童用品、代步车租赁、应急预案等提示

**输出格式:**
必须严格按照以下 JSON 返回:
{
  "city": "城市名称",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "days": [...],
  "weather_info": [...],
  "overall_suggestions": "总体建议",
  "budget": {...}
}
"""