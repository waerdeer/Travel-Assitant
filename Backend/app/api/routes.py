from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.agents.orchestrator import TripOrchestrator
from app.skills.dag import DAGContext
from app.skills.registry import skill_registry

router = APIRouter()

class PlanRequest(BaseModel):
    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD")
    preferences: str = Field(default="", description="偏好：亲子游/穷游/美食等")
    accommodation: str = Field(default="", description="住宿偏好：经济型/豪华型等")

class ChatRequest(BaseModel):
    text: str = Field(..., description="用户的自然语言输入")

@router.post("/trips", summary="生成旅行计划")
async def create_trip(req: PlanRequest):
    context = DAGContext(
        city=req.city,
        start_date=req.start_date,
        end_date=req.end_date,
        preferences=req.preferences,
        accommodation=req.accommodation,
    )
    dag = skill_registry.resolve(context)

    try:
        orchestrator = TripOrchestrator()
        result = await orchestrator.plan_trip(
            city=req.city,
            start_date=req.start_date,
            end_date=req.end_date,
            preferences=req.preferences,
            accommodation=req.accommodation,
        )
        return {"skill_used": dag.name, "plan": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat_plan", summary="自然语言对话生成行程")
async def chat_create_trip(req: ChatRequest):
    orchestrator = TripOrchestrator()
    try:
        extracted = await orchestrator.extract_params(req.text)
        
        context = DAGContext(
            city=extracted.get("city", "未知"),
            start_date=extracted.get("start_date", ""),
            end_date=extracted.get("end_date", ""),
            preferences=extracted.get("preferences", req.text),
            accommodation=extracted.get("accommodation", ""),
        )
        dag = skill_registry.resolve(context)
        
        result = await orchestrator.plan_trip(
            city=context.city,
            start_date=context.start_date,
            end_date=context.end_date,
            preferences=context.preferences,
            accommodation=context.accommodation,
        )
        return {"skill_used": dag.name, "plan": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/skills", summary="查看已注册的 Skill 列表")
async def list_skills():
    return [
        {"name": d.name, "description": d.description, "keywords": d.keywords, "nodes": list(d.nodes.keys())}
        for d in skill_registry.all()
    ]
