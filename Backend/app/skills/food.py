"""
=====================================================================
模块名称: food.py
功能描述: 专家技能：美食游，包含寻找当地特色美食和打卡餐厅的特定处理逻辑。
=====================================================================
"""

from app.skills.base import BaseSkill


class FoodTripSkill(BaseSkill):
    """美食攻略专家。"""

    @property
    def name(self) -> str:
        return "美食攻略"

    @property
    def description(self) -> str:
        return "以美食体验为核心的行程，突出本地特色餐饮"

    @property
    def keywords(self) -> list[str]:
        return ["美食", "吃", "吃货", "米其林", "小吃", "地道", "餐饮"]

    @property
    def planner_prompt(self) -> str:
        return """你是美食攻略旅行规划专家。

**专业规则（必须遵守）:**
1. 每天重点安排当地特色餐厅/小吃，标注推荐理由与人均消费
2. 三餐类型齐全（breakfast/lunch/dinner/snack）
3. 景点安排围绕美食动线，避免频繁跨区折返
4. 提前预约的餐厅在建议中注明
5. 提供必吃清单与避坑提示
6. budget 中餐饮占比显著，单独说明

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