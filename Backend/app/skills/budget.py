"""
=====================================================================
模块名称: budget.py
功能描述: 专家技能：穷游/预算控制，包含预算敏感型用户的特定处理逻辑。
=====================================================================
"""

from app.skills.base import BaseSkill


class BudgetTripSkill(BaseSkill):
    """穷游 / 预算优化专家。"""

    @property
    def name(self) -> str:
        return "穷游预算"

    @property
    def description(self) -> str:
        return "预算敏感型行程，优化交通、住宿与门票支出"

    @property
    def keywords(self) -> list[str]:
        return ["穷游", "省钱", "划算", "预算", "经济", "便宜", "低预算"]

    @property
    def planner_prompt(self) -> str:
        return """你是穷游 / 预算优化旅行规划专家。

**专业规则（必须遵守）:**
1. 优先推荐免费或低门票景点
2. 推荐经济型酒店、青旅或特色民宿，估算每晚上限
3. 交通尽量选地铁、公交等低成本方式，注明估算费用
4. 提供省钱技巧：早鸟票、联票、学生优惠、避开旺季
5. budget 各项估算从紧，给出明确的总预算区间
6. 餐饮以本地特色平价小店为主

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