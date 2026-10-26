"""On-demand, read-only discovery against an accepted plan version.

No planner, message, checkpoint, or Trip write occurs on this endpoint.
"""

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import conversation_lock
from app.db import crud
from app.db.database import get_session
from app.graph.anchors import same_city
from app.graph.geography import detail_location
from app.graph.place_policy import unavailable_place
from app.graph.tools import (
    AMAP_SERVER,
    TOOL_DETAIL,
    search_hotels,
    search_nearby_pois,
    search_restaurants,
)
from app.graph.validation import distance_km
from app.mcp.registry import mcp_client
from app.services.images import poi_images
from app.services.plan_version import plan_version

router = APIRouter(tags=["browse"])


class BrowseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    anchor_evidence_id: str = Field(min_length=1, max_length=128)
    category: Literal["hotel", "restaurant"]


async def discover(snapshot: dict, request: BrowseRequest) -> dict:
    itinerary = snapshot["itinerary"]
    day = next((day for day in itinerary["days"] if day["date"] == request.date), None)
    if not day:
        raise HTTPException(400, "日期不属于当前正式行程。")
    lookup = {e["evidence_id"]: e for e in snapshot.get("evidence", [])}
    allowed = {
        s["evidence_id"]
        for s in day["stops"]
        if lookup.get(s["evidence_id"], {}).get("category") == "attraction"
    }
    if request.category == "hotel":
        if len(itinerary["days"]) < 2 or day["date"] == itinerary["days"][-1]["date"]:
            raise HTTPException(400, "该日未安排过夜住宿；可在其他活动地点浏览美食。")
        if itinerary.get("hotel_evidence_id"):
            allowed.add(itinerary["hotel_evidence_id"])
    if request.anchor_evidence_id not in allowed:
        raise HTTPException(400, "浏览参照点不属于当天行程。")
    anchor = lookup[request.anchor_evidence_id]
    city = itinerary["city"]
    if not same_city(anchor.get("city", ""), city):
        raise HTTPException(400, "参照点城市与行程不符。")
    location = anchor["data"].get("location")
    if not location and anchor["data"].get("id"):
        try:
            detail = await asyncio.wait_for(
                mcp_client.call_tool(AMAP_SERVER, TOOL_DETAIL, {"id": anchor["data"]["id"]}),
                timeout=20,
            )
            if detail.success:
                location = detail_location(detail.content, anchor["data"]["id"])
        except Exception:
            pass
    by_coordinates = distance_km({"location": location}, {"location": location}) is not None
    queries = ["酒店", "民宿"] if request.category == "hotel" else [f"{city}特色菜", f"{city}小吃"]
    fetched = datetime.now(timezone.utc).isoformat()

    async def search(query):
        try:
            if by_coordinates:
                raw = await asyncio.wait_for(
                    search_nearby_pois.ainvoke(
                        {
                            "city": city,
                            "location": location,
                            "category": request.category,
                            "keywords": query,
                        }
                    ),
                    timeout=25,
                )
            elif request.category == "hotel":
                raw = await asyncio.wait_for(
                    search_hotels.ainvoke(
                        {
                            "city": city,
                            "poi_location": anchor["data"].get("address") or anchor["data"]["name"],
                            "budget_level": "民宿" if query == "民宿" else "中档",
                        }
                    ),
                    timeout=25,
                )
            else:
                raw = await asyncio.wait_for(
                    search_restaurants.ainvoke(
                        {
                            "city": city,
                            "poi_location": anchor["data"].get("address") or anchor["data"]["name"],
                            "food_type": query,
                        }
                    ),
                    timeout=25,
                )
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not payload.get("ok"):
                return [], False
            items = payload.get("items", [])
            return (items, True) if isinstance(items, list) else ([], False)
        except Exception:
            return [], False

    groups = await asyncio.gather(*(search(query) for query in queries))
    if not any(ok for _, ok in groups):
        raise HTTPException(502, "地图检索暂时不可用，请稍后重试。原行程未改动。")
    cards = []
    seen = set()
    # Interleave search directions rather than filling the panel from one query.
    for index in range(max((len(items) for items, _ in groups), default=0)):
        for items, _ in groups:
            if index >= len(items):
                continue
            item = items[index]
            if (
                not isinstance(item, dict)
                or not item.get("id")
                or not item.get("name")
                or unavailable_place(item)
            ):
                continue
            if item.get("cityname") and (
                not isinstance(item["cityname"], str) or not same_city(item["cityname"], city)
            ):
                continue
            if item["id"] in seen:
                continue
            km = distance_km({"location": location}, item)
            if by_coordinates and km is not None and km > 5:
                continue
            seen.add(item["id"])
            cards.append(
                {
                    "poi_id": item["id"],
                    "name": item["name"],
                    "address": item.get("address", ""),
                    "source": "高德地图 MCP",
                    "fetched_at": fetched,
                    "distance_km": round(km, 2) if km is not None else None,
                    "images": [
                        {"url": url, "source": "高德地图 MCP", "poi_id": item["id"]}
                        for url in poi_images(item)
                    ],
                }
            )
    return {
        "plan_version": request.plan_version,
        "date": request.date,
        "category": request.category,
        "anchor_evidence_id": request.anchor_evidence_id,
        "anchor_name": anchor["data"]["name"],
        "city": city,
        "relation": "以该地点坐标在5公里范围检索；距离仅为直线距离，交通待核实。"
        if by_coordinates
        else "按该地点名称或地址检索；没有可用坐标，实际距离与交通待核实。",
        "items": cards[:6],
        "notice": (
            "餐饮按城市特色方向检索，结果仍为周边餐饮候选，不代表每家均已认证为本地特色。"
            if request.category == "restaurant"
            else ""
        )
        + "仅供浏览，未选择或预订；价位、房态、营业和菜系仍需核实。"
        + ("部分检索方向未成功，可稍后重试。" if not all(ok for _, ok in groups) else ""),
    }


@router.post("/conversations/{thread_id}/browse")
async def browse_places(
    thread_id: str, request: BrowseRequest, session: AsyncSession = Depends(get_session)
):
    async with conversation_lock(thread_id):
        trip = await crud.get_trip(session, thread_id)
        if trip is None:
            raise HTTPException(404, "尚无已保存正式行程，请先完成规划。")
        snapshot = deepcopy(trip.plan_json)
        if not snapshot.get("itinerary"):
            raise HTTPException(409, "旧版行程没有可浏览的结构化地点，请重新规划。")
        if plan_version(snapshot) != request.plan_version:
            raise HTTPException(409, "行程已更新，请刷新后从新行程浏览。")
    # Release the read transaction and lock during network calls.
    await session.rollback()
    result = await discover(snapshot, request)
    async with conversation_lock(thread_id):
        trip = await crud.get_trip(session, thread_id)
        if trip is None:
            raise HTTPException(404, "会话或行程已删除。")
        if plan_version(trip.plan_json) != request.plan_version:
            raise HTTPException(409, "检索期间行程已更新，旧浏览结果已丢弃。")
    return result
