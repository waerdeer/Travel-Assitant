from app.skills.dag import DAGContext, SkillDAG
from app.skills.general_dag import GENERAL_DAG
from app.skills.family_dag import FAMILY_DAG
from app.skills.budget_dag import BUDGET_DAG
from app.skills.food_dag import FOOD_DAG


class SkillRegistry:
    """Skill 注册中心：管理所有 DAG，按用户偏好匹配。"""

    def __init__(self):
        self._dags: list[SkillDAG] = [
            GENERAL_DAG,
            FAMILY_DAG,
            BUDGET_DAG,
            FOOD_DAG,
        ]

    def register(self, dag: SkillDAG) -> None:
        self._dags.append(dag)

    def all(self) -> list[SkillDAG]:
        return list(self._dags)

#目前直接通过keyword 子串匹配关键词而不是通过llm 大脑来选择。后续可以迭代升级。
    def resolve(self, context: DAGContext) -> SkillDAG:
        """根据用户偏好匹配最合适的 DAG。未命中则返回通用 DAG。"""
        text = f"{context.preferences} {context.accommodation}"
        for dag in self._dags:
            if dag.keywords and any(k in text for k in dag.keywords):
                return dag
        return self._dags[0]


skill_registry = SkillRegistry()
