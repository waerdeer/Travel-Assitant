"""
=====================================================================
模块名称: persistence.py
功能描述: /chat_plan 的写入式持久化服务（write-through）
         把 LangGraph 的 final_state 落库为 conversation / messages / trip。
         该函数保证「永不抛出」——即使持久化失败也不影响对话响应。
=====================================================================
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.coerce import as_text
from app.db import crud
from app.db.models import AgentCheckpoint

logger = logging.getLogger("app.persistence")


def _last_ai_content(state: dict) -> str:
    """取 state.messages 中最后一条 AI 消息内容，兜底用 final_plan_md"""
    for msg in reversed(state.get("messages", [])):
        # langchain 消息对象带 type 属性
        if getattr(msg, "type", "") == "ai":
            return str(msg.content)
    return state.get("final_plan_md", "")


def _build_plan_json(state: dict) -> dict:
    """将 TripState 的中间数据组装成结构化行程 JSON"""
    return {
        "city": state.get("city"),
        "start_date": state.get("start_date"),
        "end_date": state.get("end_date"),
        "persona": state.get("persona"),
        "custom_preferences": state.get("custom_preferences"),
        "weather_context": state.get("weather_context"),
        "inspiration_list": state.get("inspiration_list", []),
        "confirmed_hotels": state.get("confirmed_hotels", []),
        "confirmed_attractions": state.get("confirmed_attractions", []),
        "rough_itinerary": state.get("rough_itinerary", ""),
        "requirements": state.get("requirements", {}),
        "itinerary": state.get("itinerary"),
        "evidence": state.get("evidence", []),
        "validation": state.get("validation", {}),
        "trace": state.get("trace", []),
        "metrics": state.get("metrics", {}),
        "accepted_plan": state.get("accepted_plan", {}),
    }


async def persist_turn(
    session: AsyncSession,
    *,
    thread_id: str,
    user_text: str,
    state: dict,
) -> bool:
    """把一个对话轮次写入数据库。永不抛出。

    - 更新/创建 conversation（城市、日期、偏好、状态）
    - 追加 user 消息 + assistant 回复
    - 若本轮产出行程（final_plan_md 非空），则 upsert trip 行
    """
    try:
        # 兜底收口：本函数的契约是「永不抛出」，那它就不应该有能力因为
        # 一个字段类型不对而回滚整个事务。
        #
        # 上游已经有两处收口（RouterOutput 的 field_validator、fallback 走
        # model_validate），这里是无条件的第三层。看似冗余，但正是因为缺了
        # 它，一个 {} 就炸掉了整轮写入：
        #     sqlite3.InterfaceError: Error binding parameter 5
        # persist_turn 是单事务的，conversations / messages / trips 一起回滚，
        # 三张表因此至今 0 行。多层收口的成本是一行 as_text，收益是写入不再
        # 因为单个字段的类型而全盘失败。
        intent = as_text(state.get("intent", "chat")) or "chat"
        city = as_text(state.get("city", ""))
        start_date = as_text(state.get("start_date", ""))
        end_date = as_text(state.get("end_date", ""))
        persona = as_text(state.get("persona", ""))
        custom_preferences = as_text(state.get("custom_preferences", ""))
        plan_md = as_text(state.get("final_plan_md", ""))

        has_plan = bool(plan_md) and intent != "chat"
        if state.get("status"):
            status = state["status"]
        elif has_plan:
            status = "completed"
        elif intent == "chat":
            status = "chat"
        else:
            status = "in_progress"

        await crud.upsert_conversation(
            session,
            thread_id=thread_id,
            city=city,
            start_date=start_date,
            end_date=end_date,
            persona=persona,
            custom_preferences=custom_preferences,
            status=status,
        )

        session.add(crud.new_message(thread_id, "user", as_text(user_text), intent))
        session.add(
            crud.new_message(
                thread_id, "assistant", as_text(_last_ai_content(state)), intent
            )
        )

        if has_plan:
            await crud.upsert_trip(
                session,
                conversation_id=thread_id,
                city=city,
                start_date=start_date,
                end_date=end_date,
                intent=intent,
                plan_json=_build_plan_json(state),
                plan_md=plan_md,
            )

        if "status" in state:
            snapshot = {k: v for k, v in state.items() if k not in ("messages", "previous_itinerary", "previous_plan_md")}
            snapshot["messages"] = [{"role": m.type, "content": str(m.content)} for m in state.get("messages", [])[-24:]]
            checkpoint = await session.get(AgentCheckpoint, thread_id)
            if checkpoint is None:
                session.add(AgentCheckpoint(thread_id=thread_id, state_json=snapshot))
            else:
                checkpoint.state_json = snapshot
        await session.commit()
        return True
    except Exception:
        await session.rollback()
        logger.exception("持久化写入失败（不影响对话响应）, thread_id=%s", thread_id)
        return False
