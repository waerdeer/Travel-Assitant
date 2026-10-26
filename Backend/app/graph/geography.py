"""Resolve only selected POIs before acceptance, within the same tool budget."""

import asyncio
from datetime import datetime, timezone
from time import perf_counter

from app.core.config import settings
from app.graph.place_policy import unavailable_place
from app.graph.tools import AMAP_SERVER, TOOL_DETAIL, extract_mcp_data
from app.mcp.registry import mcp_client


def detail_place(content, expected_id: str) -> dict | None:
    """Only a matching POI can update either coordinates or availability."""
    data = extract_mcp_data(content)
    candidates = data if isinstance(data, list) else [data]
    for obj in candidates:
        if not isinstance(obj, dict):
            continue
        pois = obj.get("pois") or [obj]
        if isinstance(pois, dict):
            pois = [pois]
        if not isinstance(pois, list):
            continue
        for poi in pois:
            if not isinstance(poi, dict) or str(poi.get("id", "")) != expected_id:
                continue
            return poi
    return None


def detail_location(content, expected_id: str) -> str | None:
    poi = detail_place(content, expected_id)
    value = poi.get("location") if poi else None
    if isinstance(value, str):
        try:
            lon, lat = map(float, value.split(","))
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                return value
        except ValueError:
            pass
    return None


async def enrich_locations(state: dict) -> dict:
    evidence = [dict(e, data=dict(e["data"])) for e in state.get("evidence", [])]
    refs = {s["evidence_id"] for d in state["itinerary"]["days"] for s in d["stops"]}
    if state["itinerary"].get("hotel_evidence_id"):
        refs.add(state["itinerary"]["hotel_evidence_id"])
    trace = list(state.get("trace", []))
    attempts = {}
    permanent = set()
    for event in trace:
        if event.get("tool") == TOOL_DETAIL:
            poi_id = event["args"]["id"]
            attempts[poi_id] = attempts.get(poi_id, 0) + 1
            if event.get("retryable") is False:
                permanent.add(poi_id)
    remaining = max(0, settings.max_tool_calls - state.get("tool_calls", 0))
    pending = [
        e
        for e in evidence
        if e["evidence_id"] in refs
        and not e["data"].get("location")
        and e["data"].get("id")
        and attempts.get(e["data"]["id"], 0) < 2
        and e["data"]["id"] not in permanent
    ][:remaining]
    # Sequential admission plus the client's account-level pacer avoids the
    # real CUQPS limit observed when four detail requests ran together.
    semaphore = asyncio.Semaphore(1)
    budget = [remaining]

    async def resolve(e):
        poi_id = e["data"]["id"]
        events = []
        async with semaphore:
            for attempt in range(2 - attempts.get(poi_id, 0)):
                if budget[0] <= 0:
                    break
                budget[0] -= 1
                started = perf_counter()
                code, retryable, location = None, False, None
                unavailable = False
                try:
                    result = await asyncio.wait_for(
                        mcp_client.call_tool(AMAP_SERVER, TOOL_DETAIL, {"id": poi_id}), timeout=25
                    )
                    code, retryable = result.error_code, result.retryable
                    if result.success:
                        poi = detail_place(result.content, poi_id)
                        location = detail_location(result.content, poi_id)
                        unavailable = bool(poi and unavailable_place(poi))
                        if unavailable:
                            # Retain the fact and its ID; filtering must not erase
                            # the user's obligation or discard the source signal.
                            e["data"].update(
                                business_status="closed",
                                availability_detail_name=str(poi.get("name", "")),
                                availability_source=TOOL_DETAIL,
                                availability_fetched_at=datetime.now(timezone.utc).isoformat(),
                            )
                        if not location and not unavailable:
                            code, retryable = "coordinates_missing", False
                except Exception as exc:
                    code, retryable = (
                        type(exc).__name__,
                        isinstance(exc, (TimeoutError, ConnectionError)),
                    )
                events.append(
                    {
                        "stage": "tool",
                        "tool": TOOL_DETAIL,
                        "args": {"id": poi_id},
                        "ok": bool(location or unavailable),
                        "count": 1 if location or unavailable else 0,
                        "has_coordinates": bool(location),
                        "unavailable": unavailable,
                        "error_code": code,
                        "retryable": retryable,
                        "attempt": attempts.get(poi_id, 0) + attempt + 1,
                        "duration_ms": round((perf_counter() - started) * 1000),
                    }
                )
                if location:
                    e["data"].update(
                        location=location,
                        location_source=TOOL_DETAIL,
                        location_fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                    break
                if unavailable:
                    break
                if not retryable:
                    break
        return events

    grouped = await asyncio.gather(*(resolve(e) for e in pending))
    events = [event for group in grouped for event in group]
    trace.extend(events)
    trace.append(
        {
            "stage": "geography",
            "summary": f"补充 {sum(e['has_coordinates'] for e in events)} 个已选地点坐标；{sum(e['unavailable'] for e in events)} 个地点被详情标记为不可用",
        }
    )
    return {
        "evidence": evidence,
        "trace": trace,
        "tool_calls": state.get("tool_calls", 0) + len(events),
    }
