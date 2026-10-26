"""Read-only images for references actually used by an accepted plan."""

from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import conversation_lock
from app.db import crud
from app.db.database import get_session
from app.graph.anchors import same_city
from app.graph.place_policy import unavailable_place
from app.services.images import poi_images
from app.services.place_photos import PhotoLoader, PhotoResult
from app.services.plan_version import plan_version

router = APIRouter(tags=["place-images"])
loader = PhotoLoader()


class PlaceImagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_id: str = Field(min_length=1, max_length=128)


def resolve_place(snapshot: dict, evidence_id: str) -> tuple[str, dict]:
    itinerary = snapshot.get("itinerary")
    if not isinstance(itinerary, dict):
        raise HTTPException(409, "旧行程缺少结构化地点，请重新规划。")
    used = {
        stop["evidence_id"] for day in itinerary.get("days", []) for stop in day.get("stops", [])
    }
    if itinerary.get("hotel_evidence_id"):
        used.add(itinerary["hotel_evidence_id"])
    place = next(
        (item for item in snapshot.get("evidence", []) if item.get("evidence_id") == evidence_id),
        None,
    )
    if (
        evidence_id not in used
        or not place
        or place.get("category") not in ("attraction", "restaurant", "hotel")
    ):
        raise HTTPException(400, "图片地点不属于当前正式行程，不能按名称查找其他地点的图片。")
    city = itinerary.get("city", "")
    if (
        not isinstance(city, str)
        or not isinstance(place.get("city"), str)
        or not same_city(place["city"], city)
    ):
        raise HTTPException(400, "地点城市与正式行程不一致。")
    if not isinstance(place.get("data"), dict):
        raise HTTPException(400, "地点缺少可核对的来源数据。")
    return city, place["data"]


@router.post("/conversations/{thread_id}/place-images")
async def place_images(
    thread_id: str, request: PlaceImagesRequest, session: AsyncSession = Depends(get_session)
):
    async with conversation_lock(thread_id):
        trip = await crud.get_trip(session, thread_id)
        if trip is None:
            raise HTTPException(404, "未找到已保存的正式行程。")
        snapshot = deepcopy(trip.plan_json)
        if plan_version(snapshot) != request.plan_version:
            raise HTTPException(409, "行程已更新，旧地点图片请求已失效。")
        city, data = resolve_place(snapshot, request.evidence_id)
    await session.rollback()
    poi_id = data.get("id")
    if (
        not isinstance(poi_id, str)
        or not poi_id.strip()
        or len(poi_id) > 128
        or unavailable_place(data)
    ):
        photos = PhotoResult("empty")
        poi_id = ""
    else:
        poi_id = poi_id.strip()
        existing = tuple(poi_images(data)[:2])
        photos = PhotoResult("ok", existing) if existing else await loader.get(city, poi_id)
    async with conversation_lock(thread_id):
        trip = await crud.get_trip(session, thread_id)
        if trip is None:
            raise HTTPException(404, "会话或行程已删除，图片请求已失效。")
        if plan_version(trip.plan_json) != request.plan_version:
            raise HTTPException(409, "检索期间行程已更新，旧地点图片已丢弃。")
    return {
        "plan_version": request.plan_version,
        "evidence_id": request.evidence_id,
        "status": photos.status,
        "images": [{"url": url, "source": "高德地图 MCP", "poi_id": poi_id} for url in photos.urls],
    }
