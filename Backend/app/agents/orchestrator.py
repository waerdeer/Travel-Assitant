"""Turn isolation, durable state restoration, execution deadline and persistence."""

import asyncio
import logging
import uuid
from time import perf_counter
from weakref import WeakValueDictionary

from langchain_core.messages import AIMessage, HumanMessage

from app.core.config import settings
from app.db.database import async_session_factory
from app.db.models import AgentCheckpoint
from app.graph.choices import selection_text
from app.graph.workflow import app_graph
from app.schemas.planning import ChoiceSelection
from app.services.persistence import persist_turn

logger = logging.getLogger(__name__)
_locks: WeakValueDictionary = WeakValueDictionary()


def conversation_lock(thread_id: str) -> asyncio.Lock:
    # Single-process serialization. Multi-worker deployments need distributed locks.
    lock = _locks.get(thread_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[thread_id] = lock
    return lock


class TripOrchestrator:
    def __init__(self):
        self.graph = app_graph

    async def plan_trip(
        self,
        thread_id: str,
        text: str,
        on_event=None,
        selection: ChoiceSelection | None = None,
        interaction_mode: str = "automatic",
        planning_strategy: str = "route_first",
    ) -> dict:
        async with conversation_lock(thread_id):
            started = perf_counter()
            async with async_session_factory() as session:
                checkpoint = await session.get(AgentCheckpoint, thread_id)
                state = dict(checkpoint.state_json) if checkpoint else {}
                if selection is not None:
                    # Validation runs under the same lock before any model/tool
                    # call or message write. A duplicate resume cannot run twice.
                    text = selection_text(state, selection)
                state["messages"] = [
                    (HumanMessage if m["role"] == "human" else AIMessage)(content=m["content"])
                    for m in state.get("messages", [])
                ] + [HumanMessage(content=text)]
                state.update(
                    trace=[],
                    metrics={},
                    error_msg=None,
                    repair_count=0,
                    tool_calls=0,
                    research_round=0,
                    reply="",
                    choice_selection=selection.model_dump() if selection else None,
                    interaction_mode=interaction_mode,
                    planning_strategy=planning_strategy,
                    run_id=uuid.uuid4().hex,
                )
                try:

                    async def execute():
                        latest = state
                        first_draft_ms = None
                        async for mode, data in self.graph.astream(
                            state,
                            {"recursion_limit": 36},
                            stream_mode=["updates", "values", "custom"],
                        ):
                            if mode == "values":
                                latest = data
                            elif mode == "custom":
                                if on_event:
                                    await on_event({**data, "run_id": state["run_id"]})
                            else:
                                for node, update in data.items():
                                    if update.get("route_draft") and first_draft_ms is None:
                                        first_draft_ms = round((perf_counter() - started) * 1000)
                                    if on_event:
                                        await on_event(
                                            {
                                                "node": node,
                                                "phase": "complete",
                                                "run_id": state["run_id"],
                                                "trace": update.get("trace", []),
                                                "validation": update.get("validation"),
                                                "metrics": update.get("metrics"),
                                                "pending_choice": update.get("pending_choice"),
                                                **(
                                                    {"route_draft": update["route_draft"]}
                                                    if "route_draft" in update
                                                    else {}
                                                ),
                                            }
                                        )
                        if first_draft_ms is not None:
                            latest["metrics"] = {
                                **latest.get("metrics", {}),
                                "time_to_draft_ms": first_draft_ms,
                            }
                        return latest

                    result = await asyncio.wait_for(
                        execute(), timeout=settings.agent_timeout_seconds
                    )
                except Exception as exc:
                    error_code = getattr(exc, "code", type(exc).__name__)
                    logger.error("Agent turn failed: %s", error_code)
                    reply = "本轮服务执行失败或超时，原有行程仍保留。请稍后重试。"
                    # Keep the previously completed state; an interrupted run must
                    # not overwrite it with a partially generated candidate.
                    result = {
                        **state,
                        "status": "failed",
                        "intent": "chat",
                        "reply": reply,
                        "error_msg": error_code,
                        "trace": [
                            {
                                "stage": "execute",
                                "status": "failed",
                                "error_code": error_code,
                            }
                        ],
                        "messages": state["messages"] + [AIMessage(content=reply)],
                    }
                    result["metrics"] = getattr(exc, "usage", state.get("metrics", {}))
                result["metrics"] = {
                    **result.get("metrics", {}),
                    "duration_ms": round((perf_counter() - started) * 1000),
                    "tool_calls": result.get("tool_calls", 0),
                    "repairs": max(0, result.get("repair_count", 0) - 1),
                }
                saved = await persist_turn(
                    session, thread_id=thread_id, user_text=text, state=result
                )
                result["persisted"] = saved
                return result
