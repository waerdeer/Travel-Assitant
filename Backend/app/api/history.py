"""
=====================================================================
模块名称: history.py
功能描述: 会话 / 消息 / 行程历史记录查询与删除接口
         （全部挂在 /api/v1 下，与 /chat_plan 平行）
=====================================================================
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import conversation_lock
from app.db import crud
from app.db.database import get_session
from app.db.models import AgentCheckpoint
from app.schemas.history import (
    ConversationDetail,
    ConversationList,
    ConversationSummary,
    MessageList,
    TripOut,
)
from app.services.plan_version import plan_version

router = APIRouter(tags=["history"])

MAX_LIMIT = 100


def _to_summary(conv, message_count: int) -> ConversationSummary:
    return ConversationSummary(
        thread_id=conv.thread_id,
        city=conv.city or None,
        start_date=conv.start_date or None,
        end_date=conv.end_date or None,
        persona=conv.persona or None,
        status=conv.status or None,
        message_count=message_count,
        updated_at=conv.updated_at,
    )


@router.get("/conversations", response_model=ConversationList, summary="会话列表")
async def list_conversations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
):
    total, rows = await crud.list_conversations(session, skip=skip, limit=limit)
    items = [_to_summary(conv, count) for conv, count in rows]
    return ConversationList(total=total, items=items)


@router.get(
    "/conversations/{thread_id}",
    response_model=ConversationDetail,
    summary="会话详情（含最近消息）",
)
async def get_conversation(
    thread_id: str,
    message_limit: int = Query(20, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
):
    conv = await crud.get_conversation(session, thread_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    # 取最近 message_limit 条，按时间倒序取再正序展示
    total, _ = await crud.list_messages(session, thread_id, skip=0, limit=1)
    _, messages = await crud.list_messages(
        session, thread_id, skip=max(0, total - message_limit), limit=message_limit
    )
    recent = sorted(
        messages[-message_limit:],
        key=lambda m: (m.created_at, m.id),
    )
    checkpoint = await session.get(AgentCheckpoint, thread_id)
    state = checkpoint.state_json if checkpoint else {}
    detail = ConversationDetail(
        **_to_summary(conv, total).model_dump(),
        recent_messages=recent,
        pending_choice=state.get("pending_choice"),
        route_draft=state.get("route_draft"),
        last_run={key: state.get(key) for key in ("status", "trace", "metrics")},
    )
    return detail


@router.get(
    "/conversations/{thread_id}/messages",
    response_model=MessageList,
    summary="会话消息列表",
)
async def list_messages(
    thread_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
):
    conv = await crud.get_conversation(session, thread_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    total, items = await crud.list_messages(session, thread_id, skip=skip, limit=limit)
    return MessageList(total=total, items=items)


@router.get(
    "/conversations/{thread_id}/trip",
    response_model=TripOut,
    summary="会话的行程计划",
)
async def get_trip(
    thread_id: str,
    session: AsyncSession = Depends(get_session),
):
    trip = await crud.get_trip(session, thread_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="trip plan not found")
    result = TripOut.model_validate(trip)
    result.version = plan_version(trip.plan_json)
    return result


@router.delete(
    "/conversations/{thread_id}",
    status_code=204,
    summary="删除会话（级联删除消息与行程）",
)
async def delete_conversation(
    thread_id: str,
    session: AsyncSession = Depends(get_session),
):
    async with conversation_lock(thread_id):
        deleted = await crud.delete_conversation(session, thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="conversation not found")
    return Response(status_code=204)
