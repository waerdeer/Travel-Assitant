"""
=====================================================================
模块名称: history.py
功能描述: 历史记录接口的 Pydantic 请求 / 响应模型
=====================================================================
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    thread_id: str
    city: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    persona: str | None = None
    status: str | None = None
    message_count: int
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    intent: str | None = None
    created_at: datetime


class ConversationDetail(ConversationSummary):
    recent_messages: list[MessageOut] = []
    pending_choice: dict | None = None
    route_draft: dict | None = None
    last_run: dict | None = None


class TripOut(BaseModel):
    version: str = ""
    model_config = ConfigDict(from_attributes=True)

    conversation_id: str
    city: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    intent: str | None = None
    plan_json: dict
    plan_md: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationList(BaseModel):
    total: int
    items: list[ConversationSummary]


class MessageList(BaseModel):
    total: int
    items: list[MessageOut]
