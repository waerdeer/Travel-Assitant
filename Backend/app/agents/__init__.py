from app.agents.base import BaseAgent, AgentContext, AgentResult

__all__ = [
    "BaseAgent",
    "AgentContext",
    "AgentResult",
    "TripOrchestrator",
]


def __getattr__(name: str):
    # 延迟导入 orchestrator，避免与 skills 层形成循环导入
    if name == "TripOrchestrator":
        from app.agents.orchestrator import TripOrchestrator
        return TripOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")