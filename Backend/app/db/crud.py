"""
=====================================================================
模块名称: crud.py
功能描述: 纯数据库读写操作（不含业务逻辑），供 routes / services 调用
=====================================================================
"""

from typing import Tuple

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentCheckpoint, Conversation, Message, Trip, _now


# ---------- 写入 ----------

async def upsert_conversation(
    session: AsyncSession,
    *,
    thread_id: str,
    city: str = "",
    start_date: str = "",
    end_date: str = "",
    persona: str = "",
    custom_preferences: str = "",
    status: str = "in_progress",
) -> Conversation:
    """创建或更新会话。仅在提供非空值时覆盖已有字段，避免聊天轮次清空行程信息。"""
    conv = await session.get(Conversation, thread_id)
    if conv is None:
        conv = Conversation(
            thread_id=thread_id,
            city=city,
            start_date=start_date,
            end_date=end_date,
            persona=persona,
            custom_preferences=custom_preferences,
            status=status,
        )
        session.add(conv)
    else:
        if city:
            conv.city = city
        if start_date:
            conv.start_date = start_date
        if end_date:
            conv.end_date = end_date
        if persona:
            conv.persona = persona
        if custom_preferences:
            conv.custom_preferences = custom_preferences
        conv.status = status
        conv.updated_at = _now()
    return conv


def new_message(conversation_id: str, role: str, content: str, intent: str = "") -> Message:
    """构造一条未持久化的消息"""
    return Message(conversation_id=conversation_id, role=role, content=content, intent=intent)


async def upsert_trip(
    session: AsyncSession,
    *,
    conversation_id: str,
    city: str,
    start_date: str,
    end_date: str,
    intent: str,
    plan_json: dict,
    plan_md: str,
) -> None:
    """按 conversation_id 唯一约束执行 SQLite 原生 upsert"""
    stmt = sqlite_insert(Trip).values(
        conversation_id=conversation_id,
        city=city,
        start_date=start_date,
        end_date=end_date,
        intent=intent,
        plan_json=plan_json,
        plan_md=plan_md,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Trip.conversation_id],
        set_={
            "city": city,
            "start_date": start_date,
            "end_date": end_date,
            "intent": intent,
            "plan_json": plan_json,
            "plan_md": plan_md,
            "updated_at": _now(),
        },
    )
    await session.execute(stmt)


# ---------- 读取 ----------

async def list_conversations(
    session: AsyncSession, skip: int = 0, limit: int = 20
) -> Tuple[int, list]:
    """返回 (总条数, [(conversation, message_count), ...])，按 updated_at 倒序"""
    total = (
        await session.execute(select(func.count(Conversation.thread_id)))
    ).scalar_one()

    msg_count = (
        select(func.count(Message.id))
        .where(Message.conversation_id == Conversation.thread_id)
        .correlate(Conversation)
        .scalar_subquery()
    )
    stmt = (
        select(Conversation, msg_count.label("message_count"))
        .order_by(Conversation.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).all())
    return total, [(row[0], row[1]) for row in rows]


async def get_conversation(session: AsyncSession, thread_id: str) -> Conversation | None:
    return await session.get(Conversation, thread_id)


async def list_messages(
    session: AsyncSession, conversation_id: str, skip: int = 0, limit: int = 100
) -> Tuple[int, list[Message]]:
    """返回 (总条数, 按时间正序的消息列表)"""
    total = (
        await session.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
        )
    ).scalar_one()

    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .offset(skip)
        .limit(limit)
    )
    items = list((await session.execute(stmt)).scalars())
    return total, items


async def get_trip(session: AsyncSession, conversation_id: str) -> Trip | None:
    stmt = select(Trip).where(Trip.conversation_id == conversation_id)
    return (await session.execute(stmt)).scalar_one_or_none()


# ---------- 删除 ----------

async def delete_conversation(session: AsyncSession, thread_id: str) -> bool:
    """删除会话（级联删除其消息与行程）。返回是否真的删除了。"""
    conv = await session.get(Conversation, thread_id)
    if conv is None:
        return False
    # Explicit removal also works for tests/engines without SQLite FK pragmas.
    checkpoint = await session.get(AgentCheckpoint, thread_id)
    if checkpoint:
        await session.delete(checkpoint)
    await session.delete(conv)
    await session.commit()
    return True
