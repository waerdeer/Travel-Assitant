"""Route-first product contract: real graph/orchestrator + isolated SQLite.

Only physical search and structured model outputs are deterministic doubles.
"""

from copy import deepcopy

import pytest
from langchain_core.messages import HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_closed_loop import candidate, evidence, requirements

from app.agents import orchestrator
from app.db.base import Base
from app.db.models import AgentCheckpoint, Trip
from app.graph import choices, drafts, pipeline, research, workflow
from app.schemas.planning import ChoiceSelection, Itinerary, RequestDecision, RouteDraft


def route():
    return {
        "city": "杭州市",
        "days": [
            {"date": "2026-11-01", "theme": "湖畔慢行", "attraction_evidence_ids": ["a1"]},
            {"date": "2026-11-02", "theme": "文化漫步", "attraction_evidence_ids": ["a2"]},
        ],
        "rationale": "以西湖周边活动为主，第二天安排文化参观，食宿稍后按路线补充。",
    }


def setup(monkeypatch, *, req=None, draft=None, plan=None, empty=False, intent="new_trip"):
    req = req or requirements()
    facts = [e.model_dump() for e in evidence()]
    calls = []

    async def ask(schema, instruction, context):
        calls.append((schema.__name__, deepcopy(context)))
        if schema is RequestDecision:
            output = RequestDecision(
                intent=intent,
                requirements=req,
                hotel_profiles=["中档", "经济型"],
                food_queries=["地方菜", "小吃"],
            )
        elif schema is RouteDraft:
            output = RouteDraft.model_validate(draft if draft is not None else route())
        else:
            data = deepcopy(plan if plan is not None else candidate())
            if plan is None and context.get("service_mode") == "browse":
                available = {e["evidence_id"] for e in context["evidence"]}
                data["service_mode"] = "browse"
                if data["hotel_evidence_id"] not in available:
                    data["hotel_evidence_id"] = None
                for day in data["days"]:
                    day["stops"] = [
                        stop for stop in day["stops"] if stop["evidence_id"] in available
                    ]
                    day["stay_anchor_evidence_id"] = day["stops"][0]["evidence_id"]
                    if not any(stop["evidence_id"] == "r1" for stop in day["stops"]):
                        day["meal_breaks"] = [
                            {
                                "anchor_evidence_id": day["stops"][0]["evidence_id"],
                                "start_time": "12:00",
                                "end_time": "13:00",
                            }
                        ]
            output = Itinerary.model_validate(data)
        return output, {"model_calls": 1, "input_tokens": 10, "output_tokens": 10}

    async def search(category, args, remaining):
        calls.append((category, deepcopy(args)))
        cat = args.get("category", category)
        results = [] if empty else [deepcopy(e) for e in facts if e["category"] == cat]
        for e in results:
            for key in ("route_relation", "route_draft_id"):
                if key in args:
                    e["data"][key] = args[key]
        return (
            results,
            [{"stage": "tool", "tool": category, "args": args, "ok": True, "count": len(results)}],
            1,
        )

    monkeypatch.setattr(pipeline, "ask_json", ask)
    monkeypatch.setattr(drafts, "ask_json", ask)
    monkeypatch.setattr(research, "execute_search", search)
    graph = workflow.build_workflow().compile()
    monkeypatch.setattr(orchestrator, "app_graph", graph)
    return graph, calls


def initial(mode="guided"):
    return {
        "messages": [HumanMessage(content="杭州两天")],
        "trace": [],
        "metrics": {},
        "repair_count": 0,
        "tool_calls": 0,
        "research_round": 0,
        "planning_strategy": "route_first",
        "interaction_mode": mode,
        "run_id": "test-run",
    }


@pytest.fixture
async def db(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'route.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(orchestrator, "async_session_factory", factory)
    yield factory
    await engine.dispose()


async def test_guided_draft_precedes_service_searches_and_never_publishes(monkeypatch, db):
    _, calls = setup(monkeypatch)
    events = []

    async def event(data):
        events.append(deepcopy(data))

    result = await orchestrator.TripOrchestrator().plan_trip(
        "draft", "杭州两天", on_event=event, interaction_mode="guided"
    )
    assert result["status"] == "awaiting_choice"
    assert result["persisted"] and not result["final_plan_md"]
    assert [name for name, _ in calls if name[0].isupper()] == ["RequestDecision", "RouteDraft"]
    draft_at = next(i for i, (name, _) in enumerate(calls) if name == "RouteDraft")
    service_calls = [
        (i, args)
        for i, (name, args) in enumerate(calls)
        if name in ("nearby", "hotel", "restaurant")
    ]
    assert service_calls and all(i > draft_at for i, _ in service_calls)
    assert all("route_draft_id" in args and "route_relation" in args for _, args in service_calls)
    progress = next(e for e in events if e.get("node") == "draft_route" and e.get("route_draft"))
    assert events.index(progress) < next(
        i for i, e in enumerate(events) if e["node"] == "research" and e["phase"] == "start"
    )
    assert progress["route_draft"]["evidence"]
    assert result["metrics"]["time_to_draft_ms"] >= 0
    assert result["pending_choice"]["draft_id"] == result["route_draft"]["draft_id"]
    async with db() as session:
        assert not (await session.execute(select(Trip))).scalars().all()
        stored = await session.get(AgentCheckpoint, "draft")
        assert stored.state_json["route_draft"] == result["route_draft"]


async def test_restart_resume_skips_understanding_and_research(monkeypatch, db):
    _, calls = setup(monkeypatch)
    first = await orchestrator.TripOrchestrator().plan_trip(
        "resume", "杭州两天", interaction_mode="guided"
    )
    calls.clear()
    # A fresh orchestrator restores the committed snapshot, no live coroutine.
    result = await orchestrator.TripOrchestrator().plan_trip(
        "resume",
        "",
        selection=ChoiceSelection(
            token=first["pending_choice"]["token"],
            hotel_evidence_id="h1",
            restaurant_evidence_ids=["r1"],
            hotel_mode="prefer",
            restaurant_mode="prefer",
        ),
    )
    assert result["status"] == "completed"
    assert [name for name, _ in calls] == ["Itinerary"]
    assert result["preferred_options"]["hotel_evidence_id"] == "h1"
    assert not result["selected_options"]
    assert result["route_draft"] is None
    assert result["accepted_plan"]["itinerary"]
    async with db() as session:
        assert (await session.execute(select(Trip))).scalar_one().plan_md


async def test_automatic_has_no_human_pause(monkeypatch):
    graph, calls = setup(monkeypatch)
    result = await graph.ainvoke(initial("automatic"))
    assert result["status"] == "completed"
    assert not result.get("pending_choice")
    assert [name for name, _ in calls if name[0].isupper()] == [
        "RequestDecision",
        "RouteDraft",
        "Itinerary",
    ]


async def test_soft_preference_does_not_filter_other_available_candidates(monkeypatch):
    graph, _ = setup(monkeypatch)
    state = await graph.ainvoke(initial())
    selection = ChoiceSelection(
        token=state["pending_choice"]["token"],
        hotel_evidence_id="h1",
        hotel_mode="prefer",
        restaurant_mode="automatic",
    )
    choices.validate_selection(state, selection)
    update = await choices.apply_selection({**state, "choice_selection": selection.model_dump()})
    assert not update["selected_options"]
    assert update["preferred_options"] == {"hotel_evidence_id": "h1"}
    changed = deepcopy(state["evidence"][0])
    changed.update(evidence_id="h2", category="hotel")
    assert "h2" in {
        e["evidence_id"]
        for e in choices.planner_evidence(
            {**state, **update, "evidence": state["evidence"] + [changed]}
        )
    }


async def test_explicit_hotel_anchor_precedes_draft_and_is_not_reselected(monkeypatch):
    graph, calls = setup(monkeypatch, req=requirements(required_hotel="真实酒店"))
    result = await graph.ainvoke(initial())
    assert calls.index(next(c for c in calls if c[0] == "named")) < calls.index(
        next(c for c in calls if c[0] == "RouteDraft")
    )
    assert not result["pending_choice"]["hotels"]
    assert result["pending_choice"]["restaurants"]
    assert not any(name == "nearby" and args["category"] == "hotel" for name, args in calls)


async def test_required_restaurant_is_at_least_once_not_exclusive_pool(monkeypatch):
    graph, _ = setup(monkeypatch, req=requirements(required_restaurants=["真实餐厅"]))
    result = await graph.ainvoke(initial())
    assert result["status"] == "awaiting_choice"
    other = deepcopy(next(e for e in result["evidence"] if e["category"] == "restaurant"))
    other["evidence_id"] = "r2"
    other["data"]["name"] = "其他餐厅"
    itinerary = candidate()
    itinerary["days"][1]["stops"][1]["evidence_id"] = "r2"
    assert not choices.selected_constraint_issues(
        {**result, "evidence": result["evidence"] + [other]}, itinerary
    )
    itinerary["days"][0]["stops"][1]["evidence_id"] = "r2"
    assert "required_restaurant_omitted" in {
        i.code
        for i in choices.selected_constraint_issues(
            {**result, "evidence": result["evidence"] + [other]}, itinerary
        )
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["days"].pop(),
        lambda d: d["days"][0].update(attraction_evidence_ids=["invented"]),
        lambda d: d["days"][1].update(attraction_evidence_ids=["a1"]),
        lambda d: d.update(city="成都市"),
    ],
)
async def test_invalid_draft_never_reaches_service_search(monkeypatch, mutation):
    draft = route()
    mutation(draft)
    graph, calls = setup(monkeypatch, draft=draft)
    result = await graph.ainvoke(initial())
    assert result["status"] == "blocked"
    assert not result.get("route_draft") and not result.get("final_plan_md")
    assert not any(name in ("nearby", "hotel", "restaurant", "Itinerary") for name, _ in calls)


async def test_missing_sources_blocks_without_draft_model(monkeypatch):
    graph, calls = setup(monkeypatch, empty=True)
    result = await graph.ainvoke(initial())
    assert result["status"] == "blocked"
    assert [name for name, _ in calls if name[0].isupper()] == ["RequestDecision"]


@pytest.mark.parametrize("change", ["draft", "requirements", "token"])
async def test_selection_is_bound_to_requirements_and_draft(monkeypatch, change):
    graph, _ = setup(monkeypatch)
    state = await graph.ainvoke(initial())
    selection = ChoiceSelection(token=state["pending_choice"]["token"], automatic=True)
    if change == "draft":
        state["route_draft"]["draft_id"] = "new-draft"
    if change == "requirements":
        state["requirements"]["end_date"] = "2026-11-03"
    if change == "token":
        selection.token = "old-token"
    with pytest.raises(choices.ChoiceConflict):
        choices.validate_selection(state, selection)


async def test_failed_new_draft_preserves_previous_formal_trip(monkeypatch, db):
    setup(monkeypatch)
    first = await orchestrator.TripOrchestrator().plan_trip(
        "accepted", "杭州两天", interaction_mode="automatic"
    )
    bad = route()
    bad["days"][0]["attraction_evidence_ids"] = ["invented"]
    setup(monkeypatch, draft=bad, intent="modify_itinerary")
    result = await orchestrator.TripOrchestrator().plan_trip("accepted", "重新规划")
    assert result["status"] == "blocked"
    assert not result["final_plan_md"]
    assert result["accepted_plan"] == first["accepted_plan"]
    async with db() as session:
        assert (await session.execute(select(Trip))).scalar_one().plan_md == first["final_plan_md"]


async def test_http_sse_history_and_conflict_keep_same_draft(monkeypatch, db):
    import json

    import httpx

    from app.db.database import get_session
    from app.main import app

    setup(monkeypatch)

    async def session_override():
        async with db() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            streamed = await client.post(
                "/api/v1/chat_plan/stream",
                json={"thread_id": "http-draft", "text": "杭州两天", "interaction_mode": "guided"},
            )
            records = []
            for block in streamed.text.split("\n\n"):
                lines = block.splitlines()
                data = next((line[6:] for line in lines if line.startswith("data: ")), None)
                kind = next((line[7:] for line in lines if line.startswith("event: ")), None)
                if data:
                    records.append((kind, json.loads(data)))
            final = next(payload for kind, payload in records if kind == "result")
            first_draft = next(
                i
                for i, (_, p) in enumerate(records)
                if p.get("node") == "draft_route" and p.get("route_draft")
            )
            services = next(
                i
                for i, (_, p) in enumerate(records)
                if p.get("node") == "research" and p.get("phase") == "start"
            )
            assert first_draft < services < len(records) - 1
            assert final["status"] == "awaiting_choice" and final["plan"]["itinerary"] is None
            restored = (await client.get("/api/v1/conversations/http-draft")).json()
            assert restored["route_draft"] == final["route_draft"]
            assert restored["pending_choice"] == final["pending_choice"]
            assert (await client.get("/api/v1/conversations/http-draft/trip")).status_code == 404
            invalid = await client.post(
                "/api/v1/chat_plan",
                json={
                    "thread_id": "http-draft",
                    "selection": {"token": "old-token", "automatic": True},
                },
            )
            assert invalid.status_code == 409
            result = (
                await client.post(
                    "/api/v1/chat_plan",
                    json={
                        "thread_id": "http-draft",
                        "selection": {"token": final["pending_choice"]["token"], "automatic": True},
                    },
                )
            ).json()
            assert result["status"] == "completed" and result["route_draft"] is None
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_draft_reports_missing_coordinates_and_cross_region_risk():
    facts = [e.model_dump() for e in evidence()]
    facts[0]["data"].pop("location")
    errors, warnings = drafts.check_draft(route(), requirements().model_dump(), facts)
    assert not errors and any("缺坐标" in w for w in warnings)
    data = route()
    data["days"][0]["attraction_evidence_ids"].append("a2")
    data["days"][1]["attraction_evidence_ids"] = ["a3"]
    facts = [e.model_dump() for e in evidence()]
    far = deepcopy(facts[1])
    far["evidence_id"] = "a3"
    far["data"]["name"] = "其他景点"
    facts[1]["data"]["location"] = "119.5,30.2"
    _, warnings = drafts.check_draft(data, requirements().model_dump(), facts + [far])
    assert any("跨区风险" in w for w in warnings)


async def test_required_anchors_cannot_be_silently_dropped_by_final_model(monkeypatch):
    bad = candidate()
    bad["hotel_evidence_id"] = "h2"
    graph, _ = setup(monkeypatch, req=requirements(required_hotel="真实酒店"), plan=bad)
    result = await graph.ainvoke(initial("automatic"))
    assert result["status"] != "completed" and not result.get("final_plan_md")
    assert "required_hotel_changed" in {i["code"] for i in result["validation"]["issues"]}
    bad = candidate()
    for day in bad["days"]:
        day["stops"] = day["stops"][:1]
    graph, _ = setup(monkeypatch, req=requirements(required_restaurants=["真实餐厅"]), plan=bad)
    result = await graph.ainvoke(initial("automatic"))
    assert result["status"] != "completed" and not result.get("final_plan_md")
    assert "required_restaurant_omitted" in {i["code"] for i in result["validation"]["issues"]}


async def test_explicit_compare_request_reopens_only_requested_category(monkeypatch):
    graph, _ = setup(monkeypatch)
    state = await graph.ainvoke(initial())
    result = await choices.review_options(
        {
            **state,
            "choice_confirmed": True,
            "review_categories": [],
            "requested_review_categories": ["hotel"],
        }
    )
    assert result["status"] == "awaiting_choice"
    assert result["pending_choice"]["hotels"] and not result["pending_choice"]["restaurants"]


async def test_draft_repairs_once_with_actual_feedback(monkeypatch):
    graph, calls = setup(monkeypatch)
    good = route()
    bad = route()
    bad["days"][0]["attraction_evidence_ids"].append("a2")
    original = drafts.ask_json
    attempts = []

    async def ask(schema, instruction, context):
        attempts.append(deepcopy(context))
        if len(attempts) == 1:
            return RouteDraft.model_validate(bad), {"model_calls": 1}
        return await original(schema, instruction, context)

    monkeypatch.setattr(drafts, "ask_json", ask)
    result = await graph.ainvoke(initial())
    assert result["status"] == "awaiting_choice"
    assert len(attempts) == 2 and attempts[1]["validation_feedback"]
    assert result["metrics"]["draft_repairs"] == 1
    assert result["route_draft"]["days"] == good["days"]


@pytest.mark.parametrize("target", ["hotel", "restaurant"])
def test_anchor_omission_retains_obligations_but_explicit_cancellation_is_possible(target):
    from app.graph.anchors import preserve_anchors
    from app.schemas.planning import AnchorChange

    old = requirements(
        required_hotel="真实酒店", required_restaurants=["真实餐厅"], reservation_notes="12:00预约"
    ).model_dump()
    name = "真实酒店" if target == "hotel" else "真实餐厅"
    req = requirements()
    preserve_anchors(old, req, [], "第二天轻松一点，其他不动")
    assert (
        req.required_hotel == "真实酒店"
        and req.required_restaurants == ["真实餐厅"]
        and req.reservation_notes
    )
    text = "取消" + name
    change = AnchorChange(target=target, action="clear", name=name, user_quote=text)
    preserve_anchors(old, req, [change], text)
    assert (not req.required_hotel) if target == "hotel" else (not req.required_restaurants)
    req = requirements()
    preserve_anchors(old, req, [change], "第二天轻松一点")
    assert req.required_hotel == "真实酒店" and req.required_restaurants == ["真实餐厅"]


@pytest.mark.parametrize(
    "text", ["真实酒店不要太吵", "真实酒店不要换", "取消博物馆预约，真实酒店不变"]
)
def test_unrelated_negative_quote_cannot_release_hotel(text):
    from app.graph.anchors import preserve_anchors
    from app.schemas.planning import AnchorChange

    old = requirements(required_hotel="真实酒店").model_dump()
    req = requirements()
    preserve_anchors(
        old,
        req,
        [AnchorChange(target="hotel", action="clear", name="真实酒店", user_quote=text)],
        text,
    )
    assert req.required_hotel == "真实酒店"


def test_explicit_replacement_and_new_trip_can_release_old_anchors():
    from app.graph.anchors import preserve_anchors
    from app.schemas.planning import AnchorChange

    old = requirements(required_hotel="真实酒店", required_restaurants=["真实餐厅"]).model_dump()
    text = "酒店换成新的酒店，必须住新的酒店"
    req = requirements(required_hotel="新的酒店")
    preserve_anchors(
        old,
        req,
        [AnchorChange(target="hotel", action="set", name="新的酒店", user_quote=text)],
        text,
    )
    assert req.required_hotel == "新的酒店" and req.required_restaurants == ["真实餐厅"]
    req = requirements()
    preserve_anchors(old, req, [], "开始一趟新的旅行", "开始一趟新的旅行")
    assert not req.required_hotel and not req.required_restaurants
    req = requirements()
    req.city = "成都市"
    preserve_anchors(old, req, [], "去成都")
    assert not req.required_hotel and not req.required_restaurants


async def test_detail_closure_withdraws_visible_draft_before_services(monkeypatch, db):
    setup(monkeypatch)

    async def close_selected(state):
        facts = deepcopy(state["evidence"])
        for fact in facts:
            if fact["evidence_id"] == "a1":
                fact["data"]["business_status"] = "closed"
        return {
            "evidence": facts,
            "trace": state["trace"] + [{"stage": "geography", "summary": "详情确认关闭"}],
        }

    monkeypatch.setattr(drafts, "enrich_locations", close_selected)
    events = []

    async def event(payload):
        events.append(deepcopy(payload))

    result = await orchestrator.TripOrchestrator().plan_trip(
        "closed-draft", "杭州两天", on_event=event
    )
    assert (
        result["status"] == "blocked" and not result["route_draft"] and not result["final_plan_md"]
    )
    assert any(e.get("route_draft") for e in events)
    assert any("route_draft" in e and e["route_draft"] is None for e in events)
    assert not any(e["node"] == "research" for e in events)


async def test_route_first_retains_fresh_closure_during_named_refresh(monkeypatch):
    graph, calls = setup(
        monkeypatch, req=requirements(required_hotel="真实酒店"), intent="modify_itinerary"
    )
    facts = [e.model_dump() for e in evidence()]
    next(e for e in facts if e["category"] == "hotel")["data"]["business_status"] = "closed"
    result = await graph.ainvoke(
        {
            **initial(),
            "evidence": facts,
            "requirements": requirements(required_hotel="真实酒店").model_dump(),
        }
    )
    assert result["status"] == "blocked" and not result["route_draft"]
    assert any(name == "named" for name, _ in calls)
    assert not any(name == "RouteDraft" for name, _ in calls)
    assert any(
        e["category"] == "hotel" and e["data"].get("business_status") == "closed"
        for e in result["evidence"]
    )


def test_city_suffix_alias_cannot_erase_anchors_but_regions_are_distinct():
    from app.graph.anchors import preserve_anchors, same_city

    old = requirements(required_hotel="真实酒店", required_restaurants=["真实餐厅"]).model_dump()
    req = requirements()
    req.city = "杭州"
    preserve_anchors(old, req, [], "第二天轻松一点")
    assert req.required_hotel == "真实酒店" and req.required_restaurants == ["真实餐厅"]
    assert same_city("杭州", "杭州市")
    assert not same_city("阿勒泰市", "阿勒泰地区")


async def test_profile_empty_nearby_expands_city_with_truthful_relation(monkeypatch):
    import json

    calls = []

    class Nearby:
        name = "nearby"

        async def ainvoke(self, args):
            calls.append(("nearby", args))
            return json.dumps({"ok": True, "items": []})

    class Hotel:
        name = "hotel"

        async def ainvoke(self, args):
            calls.append(("hotel", args))
            return json.dumps(
                {"ok": True, "items": [{"id": "city-hotel", "name": "城区酒店", "address": "杭州"}]}
            )

    monkeypatch.setitem(research.TOOLS, "nearby", Nearby())
    monkeypatch.setitem(research.TOOLS, "hotel", Hotel())
    facts, trace, count = await research.execute_search(
        "nearby",
        {
            "city": "杭州市",
            "location": "120.14,30.24",
            "category": "hotel",
            "keywords": "中档",
            "hotel_profile": "中档",
            "route_draft_id": "draft-1",
            "route_relation": "以西湖为检索参照",
        },
        2,
    )
    assert count == 2 and [name for name, _ in calls] == ["nearby", "hotel"]
    assert calls[1][1]["poi_location"] == "" and calls[1][1]["budget_level"] == "中档"
    assert (
        "全市" in facts[0]["data"]["route_relation"]
        and facts[0]["data"]["route_draft_id"] == "draft-1"
    )
    assert all("route_relation" not in args for _, args in calls)
