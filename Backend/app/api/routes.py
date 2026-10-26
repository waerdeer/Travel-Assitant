import asyncio
import json
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from app.agents.orchestrator import TripOrchestrator
from app.graph.choices import ChoiceConflict
from app.schemas.planning import ChoiceSelection
from app.services.plan_version import plan_version

router = APIRouter()


class ChatRequest(BaseModel):
    thread_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    text: str = Field(default="", max_length=4000)
    selection: ChoiceSelection | None = None
    interaction_mode: Literal["guided", "automatic"] = "automatic"
    planning_strategy: Literal["route_first", "legacy"] = "route_first"

    @model_validator(mode="after")
    def nonblank(self):
        if not self.text.strip() and self.selection is None:
            raise ValueError("请输入旅行需求")
        self.text = self.text.strip()
        return self


@router.post("/chat_plan", summary="闭环旅行规划：澄清、检索、校验与有限修正")
async def chat_create_trip(req: ChatRequest):
    try:
        result = await TripOrchestrator().plan_trip(
            thread_id=req.thread_id,
            text=req.text,
            selection=req.selection,
            interaction_mode=req.interaction_mode,
            planning_strategy=req.planning_strategy,
        )
    except ChoiceConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return response_body(req.thread_id, result)


def response_body(thread_id: str, result: dict) -> dict:
    plan_md = result.get("final_plan_md", "") if result.get("intent") != "chat" else ""
    return {
        "thread_id": thread_id,
        "status": result.get("status"),
        "reply": result.get("reply", ""),
        "skill_used": result.get("intent", "chat"),
        "plan": {
            "city": result.get("city"),
            "start_date": result.get("start_date"),
            "end_date": result.get("end_date"),
            "plan_content": plan_md,
            "version": plan_version(result) if plan_md else None,
            "itinerary": result.get("itinerary") if plan_md else None,
        },
        "requirements": result.get("requirements", {}),
        "validation": result.get("validation", {}),
        "evidence": result.get("evidence", []),
        "trace": result.get("trace", []),
        "metrics": result.get("metrics", {}),
        "degraded": bool(result.get("error_msg")),
        "error_msg": result.get("error_msg"),
        "persisted": result.get("persisted", False),
        "pending_choice": result.get("pending_choice"),
        "selected_options": result.get("selected_options", {}),
        "preferred_options": result.get("preferred_options", {}),
        "route_draft": result.get("route_draft"),
        "run_id": result.get("run_id"),
    }


@router.post("/chat_plan/stream", summary="按实际图节点完成事件流式返回执行进度")
async def stream_trip(req: ChatRequest):
    async def events():
        queue = asyncio.Queue()

        async def on_event(event):
            await queue.put(("progress", event))

        async def run():
            try:
                result = await TripOrchestrator().plan_trip(
                    req.thread_id,
                    req.text,
                    on_event=on_event,
                    selection=req.selection,
                    interaction_mode=req.interaction_mode,
                    planning_strategy=req.planning_strategy,
                )
                await queue.put(("result", response_body(req.thread_id, result)))
            except ChoiceConflict as exc:
                await queue.put(("error", {"message": str(exc)}))
            except Exception:
                await queue.put(
                    ("error", {"message": "服务执行异常，请检查服务是否已完成初始化。"})
                )

        task = asyncio.create_task(run())
        try:
            yield "event: start\ndata: {}\n\n"
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if kind in ("result", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
