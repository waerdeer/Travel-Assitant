"""
=====================================================================
模块名称: models.py
功能描述: SQLAlchemy 2.0 异步 ORM 模型定义
         - conversations : 会话表（thread_id 为主键）
         - messages      : 消息表（对话历史）
         - trips         : 行程计划表（结构化 JSON + 最终 Markdown）
=====================================================================
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Conversation(Base):
    """一次旅行规划会话（以 thread_id 为主键，对应 LangGraph 的 thread_id）"""

    __tablename__ = "conversations"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    city: Mapped[str] = mapped_column(String(128), default="")
    start_date: Mapped[str] = mapped_column(String(20), default="")
    end_date: Mapped[str] = mapped_column(String(20), default="")
    persona: Mapped[str] = mapped_column(String(64), default="")
    custom_preferences: Mapped[str] = mapped_column(Text, default="")
    # in_progress | completed | chat
    status: Mapped[str] = mapped_column(String(32), default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    trip: Mapped[Trip | None] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    __table_args__ = (Index("ix_conversations_updated_at", "updated_at"),)


class Message(Base):
    """会话内的一条消息"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("conversations.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    # "user" | "assistant"
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    # 该轮对话的意图（denormalized，便于统计）
    intent: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )


class Trip(Base):
    """最终生成的行程计划（结构化 JSON + Markdown）"""

    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("conversations.thread_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    city: Mapped[str] = mapped_column(String(128), default="")
    start_date: Mapped[str] = mapped_column(String(20), default="")
    end_date: Mapped[str] = mapped_column(String(20), default="")
    intent: Mapped[str] = mapped_column(String(32), default="")
    # 结构化行程数据（城市/日期/天气/酒店/景点/草案等）
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # 最终交付给用户的 Markdown 行程单
    plan_md: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="trip")


class AgentCheckpoint(Base):
    """Latest complete turn; JSON primitives only, no pickle deserialization."""

    __tablename__ = "agent_checkpoints"
    thread_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.thread_id", ondelete="CASCADE"), primary_key=True
    )
    state_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
