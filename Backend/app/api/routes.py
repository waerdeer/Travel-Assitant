import uuid
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.agents.orchestrator import TripOrchestrator

router = APIRouter()

class ChatRequest(BaseModel):
    # 前端现在需要传 thread_id 来追踪会话
    thread_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="会话ID")
    text: str = Field(..., description="用户的自然语言输入")

@router.post("/chat_plan", summary="自然语言对话生成行程 (支持多轮记忆)")
async def chat_create_trip(req: ChatRequest):
    orchestrator = TripOrchestrator()
    try: 
        # 直接透传 thread_id 和文本给 Orchestrator
        result = await orchestrator.plan_trip(
            thread_id=req.thread_id,
            text=req.text
        )
        return {
            "skill_used": result.get("intent", "chat"), 
            "plan": result
        }
    except Exception as e:
        import traceback; traceback.print_exc(); raise HTTPException(status_code=500, detail=str(e))
