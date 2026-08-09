"""
=====================================================================
模块名称: base.py
功能描述: 智能体基类（BaseAgent），定义所有智能体的标准输入/输出契约及核心执行接口。
=====================================================================
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

#定义所有agent的输入输出，统一接口

@dataclass
class AgentContext:
    city: str
    start_date: str
    end_date: str
    preferences: str = ""
    accommodation: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

#agent输出数据格式
@dataclass
class AgentResult:
    success: bool
    data: Any = None
    error: Optional[str] = None
    raw_response: Optional[str] = None

#定义所有agent的基类
class BaseAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult:
        ...
