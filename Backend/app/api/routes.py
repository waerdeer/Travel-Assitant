from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.agents.orchestrator import TripOrchestrator
from app.agents.base import AgentContext
from app.schemas import TripPlan


router = APIRouter()


class PlanRequest(BaseModel):
    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD")
    preferences: str = Field(default="", description="偏好：亲子游/穷游/美食等")
    accommodation: str = Field(default="", description="住宿偏好：经济型/豪华型等")


class PlanResponse(BaseModel):
    plan: TripPlan
    skill_used: str = Field(..., description="实际匹配到的 Skill 名称")


@router.post("/trips", response_model=PlanResponse, summary="生成旅行计划")
async def create_trip(req: PlanRequest):
    orchestrator = TripOrchestrator()
    context = AgentContext(
        city=req.city,
        start_date=req.start_date,
        end_date=req.end_date,
        preferences=req.preferences,
        accommodation=req.accommodation,
    )
    skill = orchestrator.router.route(context)
    try:
        plan = await orchestrator.plan_trip(
            city=req.city,
            start_date=req.start_date,
            end_date=req.end_date,
            preferences=req.preferences,
            accommodation=req.accommodation,
        )
        return PlanResponse(plan=plan, skill_used=skill.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills", summary="查看已注册的 Skill 列表")
async def list_skills():
    from app.skills import skill_registry
    return [{"name": s.name, "description": s.description, "keywords": s.keywords}
            for s in skill_registry.all()]
