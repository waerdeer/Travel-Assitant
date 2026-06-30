from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentContext:
    city: str
    start_date: str
    end_date: str
    preferences: str = ""
    accommodation: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    success: bool
    data: Any = None
    error: Optional[str] = None
    raw_response: Optional[str] = None


class BaseAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult:
        ...
