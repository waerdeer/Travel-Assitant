"""Bounded tool execution: policy is enforced in code, not just a prompt."""

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from time import perf_counter

from app.core.config import settings
from app.graph.place_policy import explicitly_operating, unavailable_place
from app.graph.schedule import needs_attractions
from app.graph.tools import (
    get_weather_and_climate,
    search_hotels,
    search_named_place,
    search_nearby_pois,
    search_restaurants,
    search_travel_inspiration,
)
from app.schemas.planning import Evidence, Requirements

TOOLS = {
    "weather": get_weather_and_climate,
    "attraction": search_travel_inspiration,
    "hotel": search_hotels,
    "restaurant": search_restaurants,
    "nearby": search_nearby_pois,
    "named": search_named_place,
}


def model_evidence(items: list[dict]) -> list[dict]:
    """Images are presentation assets, not input to the text planner."""
    return [
        {**item, "data": {key: value for key, value in item["data"].items() if key != "image_urls"}}
        for item in items
    ]


def fact_time(item: dict) -> datetime:
    """A newly observed closure has its own lifetime, not the old POI's age."""
    observed = datetime.fromisoformat(item["fetched_at"])
    signal_time = item["data"].get("availability_fetched_at")
    if unavailable_place(item["data"]) and isinstance(signal_time, str):
        try:
            confirmed = datetime.fromisoformat(signal_time)
            if confirmed.tzinfo is not None and observed.tzinfo is not None:
                observed = max(observed, confirmed)
        except ValueError:
            pass
    return observed


def fresh_evidence(
    items: list[dict], city: str, *, include_unavailable: bool = False
) -> list[dict]:
    now = datetime.now(timezone.utc)
    fresh = []
    for item in items:
        try:
            evidence = Evidence.model_validate(item)
            age = (now - fact_time(evidence.model_dump())).total_seconds()
            ttl = 3600 if evidence.category == "weather" else 6 * 3600
            if (
                evidence.city == city
                and 0 <= age < ttl
                and (include_unavailable or not unavailable_place(evidence.data))
            ):
                fresh.append(evidence.model_dump())
        except (ValueError, TypeError):
            continue
    return fresh


def merge_evidence(items: list[dict]) -> list[dict]:
    """Absence of a status field is not evidence that a known closure ended."""
    merged = {}
    for item in items:
        ref = item["evidence_id"]
        previous = merged.get(ref)
        if previous and fact_time(item) < fact_time(previous):
            continue
        if previous and unavailable_place(previous["data"]):
            old_time = fact_time(previous)
            new_time = fact_time(item)
            if not (
                new_time > old_time
                and (explicitly_operating(item["data"]) or unavailable_place(item["data"]))
            ):
                item = {
                    **item,
                    "fetched_at": previous["fetched_at"],
                    "data": {
                        **item["data"],
                        "business_status": "closed",
                        "availability_detail_name": previous["data"].get(
                            "availability_detail_name", previous["data"].get("name", "")
                        ),
                        "availability_source": previous["data"].get(
                            "availability_source", previous["source"]
                        ),
                        "availability_fetched_at": old_time.isoformat(),
                    },
                }
        merged[ref] = item
    return list(merged.values())


async def execute_search(
    category: str, args: dict, remaining: int
) -> tuple[list[dict], list[dict], int]:
    records, evidence = [], []
    tool = TOOLS[category]
    evidence_category = args["category"] if category in ("nearby", "named") else category
    # A maximum of two physical calls for this task, even if the model asks for more.
    for attempt in range(min(2, remaining)):
        started = perf_counter()
        tool_args = {k: v for k, v in args.items() if k not in ("route_relation", "route_draft_id")}
        try:
            payload = json.loads(await asyncio.wait_for(tool.ainvoke(tool_args), timeout=25))
            if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
                raise ValueError("invalid tool envelope")
        except Exception as exc:
            payload = {
                "ok": False,
                "error": {
                    "code": type(exc).__name__,
                    "retryable": isinstance(exc, (TimeoutError, ConnectionError)),
                },
            }
        # Trace exposes execution facts, never hidden chain-of-thought or credentials.
        records.append(
            {
                "stage": "tool",
                "tool": tool.name,
                "args": tool_args.copy(),
                "attempt": attempt + 1,
                "ok": payload.get("ok", False),
                "count": len(payload.get("items") or []),
                "error_code": (payload.get("error") or {}).get("code"),
                "retryable": (payload.get("error") or {}).get("retryable"),
                "duration_ms": round((perf_counter() - started) * 1000),
            }
        )
        if payload.get("ok") and payload.get("items"):
            for data in payload["items"]:
                if not isinstance(data, dict):
                    continue
                key = data.get("id") or data.get("date") or data.get("name")
                if not key:
                    continue
                data = {
                    **data,
                    "retrieval_hint": args.get("budget_level")
                    or args.get("food_type")
                    or args.get("keywords", "")
                    or args.get("name", ""),
                    "retrieval_area": args.get("poi_location", ""),
                    **(
                        {"route_relation": args["route_relation"]}
                        if args.get("route_relation")
                        else {}
                    ),
                    **(
                        {"route_draft_id": args["route_draft_id"]}
                        if args.get("route_draft_id")
                        else {}
                    ),
                }
                digest = hashlib.sha256(
                    f"{args['city']}:{evidence_category}:{key}".encode()
                ).hexdigest()[:12]
                evidence.append(
                    Evidence(
                        evidence_id=f"{evidence_category}:{digest}",
                        category=evidence_category,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        city=args["city"],
                        data=data,
                    ).model_dump()
                )
            break
        if not payload.get("ok") and not (payload.get("error") or {}).get("retryable"):
            break
        if category == "named" and payload.get("ok"):
            break
        # Successful-empty searches may broaden once. Permanent failures never retry.
        if category == "attraction":
            args = {**args, "keywords": "风景名胜 公园 博物馆"}
        elif category in ("hotel", "restaurant"):
            args = {**args, "poi_location": ""}
            if args.get("route_relation"):
                args["route_relation"] = (
                    "草案区域未找到候选，已扩大到全市检索；与每日路线的关系尚待核实。"
                )
        elif category == "nearby":
            if args.get("hotel_profile"):
                # Keep the lodging direction when expanding the area; don't
                # repeat an identical around query or relabel homestays.
                profile = args["hotel_profile"]
                args = {
                    "city": args["city"],
                    "poi_location": "",
                    "budget_level": profile,
                    "route_relation": "草案区域未找到该住宿方向，已扩大到全市检索；与每日路线的关系尚待核实。",
                    **(
                        {"route_draft_id": args["route_draft_id"]}
                        if args.get("route_draft_id")
                        else {}
                    ),
                }
                category, tool = "hotel", TOOLS["hotel"]
            else:
                args = {**args, "keywords": ""}
    return evidence, records, len(records)


async def collect_evidence(state: dict) -> dict:
    req, decision = state["requirements"], state["decision"]
    evidence = fresh_evidence(state.get("evidence", []), req["city"], include_unavailable=True)
    existing = {e["category"] for e in evidence if not unavailable_place(e["data"])}
    city = req["city"]
    tasks = []
    on_demand = (
        state.get("planning_strategy") == "route_first"
        and state.get("interaction_mode") == "automatic"
    )
    route_only = state.get("research_stage") == "route_only" or on_demand
    if "weather" not in existing:
        tasks.append(("weather", {"city": city}))
    if "attraction" not in existing and needs_attractions(Requirements.model_validate(req)):
        queries = list(
            dict.fromkeys(
                req.get("must_visit", [])
                + (decision.get("attraction_queries") or ["风景名胜 公园 博物馆"])
            )
        )
        for query in queries[:3]:
            tasks.append(("attraction", {"city": city, "keywords": query, "max_results": 10}))
    else:
        names = [e["data"].get("name", "") for e in evidence if e["category"] == "attraction"]
        for query in req.get("must_visit", []):
            if not any(query in name for name in names):
                tasks.append(("attraction", {"city": city, "keywords": query, "max_results": 5}))
    # Explicit anchors precede the route; ordinary meal/stay suggestions follow it.
    from app.graph.anchors import name_matches

    required = [("hotel", req.get("required_hotel", ""))] + [
        ("restaurant", name) for name in req.get("required_restaurants", [])
    ]
    for category, name in required:
        if name and not any(
            e["category"] == category
            and not unavailable_place(e["data"])
            and name_matches(name, e["data"].get("name", ""))
            for e in evidence
        ):
            tasks.append(("named", {"city": city, "name": name, "category": category}))
    draft_id = (state.get("route_draft") or {}).get("draft_id")

    def route_missing(category):
        return bool(draft_id) and not any(
            e["category"] == category
            and e["data"].get("route_draft_id") == draft_id
            and not unavailable_place(e["data"])
            for e in evidence
        )

    if (
        not route_only
        and ("hotel" not in existing or route_missing("hotel"))
        and not req.get("required_hotel")
        and req["start_date"] != req["end_date"]
    ):
        for profile in dict.fromkeys(
            decision.get("hotel_profiles") or [decision.get("hotel_budget_level", "中档")]
        ):
            tasks.append(
                (
                    "hotel",
                    {
                        "city": city,
                        "poi_location": decision.get("hotel_area", ""),
                        "budget_level": profile,
                    },
                )
            )
    if not route_only and ("restaurant" not in existing or route_missing("restaurant")):
        for food_query in dict.fromkeys(
            decision.get("food_queries") or [decision.get("food_query") or "当地菜"]
        ):
            tasks.append(
                (
                    "restaurant",
                    {
                        "city": city,
                        "poi_location": decision.get("hotel_area", ""),
                        "food_type": food_query,
                    },
                )
            )
    if (
        not route_only
        and state.get("planning_strategy") == "route_first"
        and state.get("route_draft")
    ):
        lookup = {e["evidence_id"]: e for e in evidence}
        anchors = [
            (day, lookup[ref])
            for day in state["route_draft"]["days"]
            for ref in day["attraction_evidence_ids"]
            if ref in lookup
        ]
        related_tasks = []
        for index, (category, args) in enumerate(tasks):
            if category in ("hotel", "restaurant") and anchors:
                day, anchor = anchors[0 if category == "hotel" else index % len(anchors)]
                relation = f"以 {day['date']} 的「{anchor['data']['name']}」为检索参照，实际距离与交通仍待检查。"
                location = anchor["data"].get("location")
                if location:
                    args = {
                        "city": city,
                        "location": location,
                        "category": category,
                        "keywords": args.get("budget_level") or args.get("food_type", ""),
                        **({"hotel_profile": args["budget_level"]} if category == "hotel" else {}),
                        "route_relation": relation,
                        "route_draft_id": draft_id,
                    }
                    category = "nearby"
                else:
                    args = {
                        **args,
                        "poi_location": anchor["data"].get("address") or anchor["data"]["name"],
                        "route_relation": relation,
                        "route_draft_id": draft_id,
                    }
            related_tasks.append((category, args))
        tasks = related_tasks
    # A geographically bad candidate needs new evidence, not another generation
    # from the same unusable city-wide restaurant list.
    codes = {issue["code"] for issue in state.get("validation", {}).get("issues", [])}
    spatial = bool(codes & {"long_transfer", "distant_hotel"})
    if spatial and not on_demand and state.get("itinerary"):
        lookup = {e["evidence_id"]: e for e in evidence}
        anchors = []
        for day in state["itinerary"]["days"]:
            for stop in day["stops"]:
                place = lookup.get(stop["evidence_id"], {})
                location = place.get("data", {}).get("location")
                if place.get("category") == "attraction" and location:
                    if location not in anchors:
                        anchors.append(location)
                    break
        if anchors:
            refresh = {"restaurant"} if "long_transfer" in codes else set()
            if "distant_hotel" in codes:
                refresh.add("hotel")
            # Evidence is a fact store. Empty repair searches must never erase
            # the user's selected facts or masquerade as source expiration.
            tasks = []
            for kind in sorted(refresh):
                for location in anchors[: 2 if kind == "restaurant" else 1]:
                    tasks.append(
                        (
                            "nearby",
                            {
                                "city": city,
                                "location": location,
                                "category": kind,
                                "keywords": decision.get("food_query", "")
                                if kind == "restaurant"
                                else "",
                            },
                        )
                    )
    calls = state.get("tool_calls", 0)
    previous_facts = {
        (e["evidence_id"], e["data"].get("name"), e["data"].get("location")) for e in evidence
    }
    spatial_attempted = False
    spatial_new_facts = False
    trace = list(state.get("trace", []))
    if spatial:
        trace.append({"stage": "research", "summary": "地理校验发现跨区冲突，改为景点坐标周边检索"})
    permanent_failures = {
        e.get("tool")
        for e in trace
        if e.get("stage") == "tool" and e.get("ok") is False and e.get("retryable") is False
    }
    for category, args in tasks:
        if TOOLS[category].name in permanent_failures:
            continue
        if calls >= settings.max_tool_calls:
            trace.append(
                {
                    "stage": "research",
                    "status": "budget_exhausted",
                    "summary": "达到本轮工具调用上限",
                }
            )
            break
        found, events, count = await execute_search(category, args, settings.max_tool_calls - calls)
        if spatial and category == "nearby" and count:
            spatial_attempted = True
            spatial_new_facts |= any(
                not unavailable_place(e["data"])
                and (e["evidence_id"], e["data"].get("name"), e["data"].get("location"))
                not in previous_facts
                for e in found
            )
        calls += count
        trace.extend(events)
        evidence.extend(found)
    evidence = merge_evidence(evidence)
    trace.append(
        {
            "stage": "research",
            "summary": f"证据收集完成，共 {len(evidence)} 条，本轮累计调用 {calls} 次工具",
            "round": state.get("research_round", 0) + 1,
        }
    )
    categories = {e["category"] for e in evidence if not unavailable_place(e["data"])}
    missing = [
        c
        for c in (("attraction",) if route_only else ("attraction", "restaurant"))
        if c not in categories
        and (c != "attraction" or needs_attractions(Requirements.model_validate(req)))
    ]
    if not route_only and req["start_date"] != req["end_date"] and "hotel" not in categories:
        missing.append("hotel")
    return {
        "evidence": evidence,
        "trace": trace,
        "tool_calls": calls,
        "research_round": state.get("research_round", 0) + 1,
        "spatial_repair_no_progress": spatial_attempted and not spatial_new_facts,
        "error_msg": "未能获取部分实时数据：" + "、".join(missing) if missing else None,
        # Preserve the old data keys for the existing history API and learning scripts.
        "inspiration_list": [e["data"] for e in evidence if e["category"] == "attraction"],
        "confirmed_attractions": [e["data"] for e in evidence if e["category"] == "attraction"],
        "confirmed_hotels": [e["data"] for e in evidence if e["category"] == "hotel"],
    }


async def collect_route_evidence(state: dict) -> dict:
    update = await collect_evidence({**state, "research_stage": "route_only"})
    # Initial route discovery does not consume the later spatial-repair round.
    update["research_round"] = state.get("research_round", 0)
    return update
