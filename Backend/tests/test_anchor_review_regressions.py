"""Regressions reproduced by the independent product review (rounds 1 and 2)."""

from copy import deepcopy

import pytest
from test_closed_loop import candidate, requirements
from test_route_first import db as db
from test_route_first import setup

from app.agents import orchestrator
from app.graph import anchors, drafts, pipeline, research
from app.schemas.planning import AnchorChange, RequestDecision


@pytest.mark.asyncio
@pytest.mark.parametrize("anchor", ["hotel", "restaurant"])
async def test_pace_edit_cannot_erase_existing_explicit_anchor(monkeypatch, db, anchor):
    req = (
        requirements(required_hotel="真实酒店")
        if anchor == "hotel"
        else requirements(required_restaurants=["真实餐厅"])
    )
    setup(monkeypatch, req=req)
    first = await orchestrator.TripOrchestrator().plan_trip(
        "anchor-persist",
        "已订真实酒店，别换" if anchor == "hotel" else "一定要去真实餐厅",
        interaction_mode="automatic",
    )
    assert first["status"] == "completed"
    changed = candidate()
    if anchor == "hotel":
        changed["hotel_evidence_id"] = "h2"
    else:
        for day in changed["days"]:
            for stop in day["stops"]:
                if stop["evidence_id"] == "r1":
                    stop["evidence_id"] = "r2"
    # Valid structured understanding response omits the old required field.
    setup(monkeypatch, req=requirements(pace="relaxed"), intent="modify_itinerary", plan=changed)
    physical = research.execute_search

    async def search(category, args, remaining):
        found, events, count = await physical(category, args, remaining)
        cat = args.get("category", category)
        if category != "named" and cat == anchor and found:
            other = deepcopy(found[0])
            other["evidence_id"] = "h2" if anchor == "hotel" else "r2"
            other["data"].update(
                id=other["evidence_id"], name="其他酒店" if anchor == "hotel" else "其他餐厅"
            )
            found.append(other)
        return found, events, count

    monkeypatch.setattr(research, "execute_search", search)
    second = await orchestrator.TripOrchestrator().plan_trip(
        "anchor-persist", "第二天轻松一点，其他不动", interaction_mode="automatic"
    )
    assert second["status"] not in ("completed", "degraded") or (
        second["itinerary"]["hotel_evidence_id"] == "h1"
        if anchor == "hotel"
        else any(s["evidence_id"] == "r1" for d in second["itinerary"]["days"] for s in d["stops"])
    )


@pytest.mark.asyncio
async def test_explicit_hotel_geographic_risk_visible_in_draft(monkeypatch):
    from test_route_first import initial

    graph, calls = setup(monkeypatch, req=requirements(required_hotel="真实酒店"))
    physical = research.execute_search

    async def search(category, args, remaining):
        found, events, count = await physical(category, args, remaining)
        for e in found:
            if e["category"] == "hotel":
                e["data"]["location"] = "120.90,30.24"
        return found, events, count

    monkeypatch.setattr(research, "execute_search", search)
    result = await graph.ainvoke(initial())
    assert result["status"] == "awaiting_choice"
    assert any(
        "酒店" in w or "住宿" in w or "跨区" in w or "距离" in w
        for w in result["route_draft"]["warnings"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_succeeds", [False, True])
async def test_draft_repair_is_bounded_and_invalid_content_never_streamed(
    monkeypatch, db, repair_succeeds
):
    from test_route_first import route

    from app.schemas.planning import RouteDraft

    setup(monkeypatch)
    valid = route()
    invalid = deepcopy(valid)
    invalid["days"][0]["attraction_evidence_ids"] = ["invented"]
    attempts = []

    async def draft_model(schema, instruction, context):
        attempts.append(deepcopy(context))
        return RouteDraft.model_validate(
            valid if repair_succeeds and len(attempts) > 1 else invalid
        ), {"model_calls": 1}

    monkeypatch.setattr(drafts, "ask_json", draft_model)
    events = []

    async def event(payload):
        events.append(deepcopy(payload))

    result = await orchestrator.TripOrchestrator().plan_trip(
        "bounded-draft", "杭州两天", on_event=event, interaction_mode="guided"
    )
    assert len(attempts) == 2 and attempts[1]["validation_feedback"]
    assert result["metrics"]["draft_repairs"] == 1
    visible = [e["route_draft"] for e in events if e.get("route_draft")]
    assert all("invented" not in d["days"][0]["attraction_evidence_ids"] for d in visible)
    if repair_succeeds:
        assert result["status"] == "awaiting_choice" and visible
    else:
        assert result["status"] == "blocked" and not visible and not result["final_plan_md"]


@pytest.mark.parametrize("target,name", [("hotel", "真实酒店"), ("restaurant", "真实餐厅")])
@pytest.mark.parametrize("fragment", [False, True])
def test_negated_cancellation_cannot_release_anchor(target, name, fragment):
    old = requirements(required_hotel="真实酒店", required_restaurants=["真实餐厅"]).model_dump()
    proposed = requirements()
    text = "不要取消" + name + "，第二天轻松一点"
    quote = "取消" + name if fragment else text
    anchors.preserve_anchors(
        old,
        proposed,
        [AnchorChange(target=target, action="clear", name=name, user_quote=quote)],
        text,
    )
    assert proposed.required_hotel == "真实酒店" and proposed.required_restaurants == ["真实餐厅"]


@pytest.mark.parametrize("text", ["不是新的旅行，只是重新规划第二天", "不要重新开始，保留这趟行程"])
def test_negated_new_trip_cannot_reset_anchors(text):
    old = requirements(required_hotel="真实酒店", required_restaurants=["真实餐厅"]).model_dump()
    proposed = requirements()
    anchors.preserve_anchors(old, proposed, [], text, text)
    assert proposed.required_hotel == "真实酒店" and proposed.required_restaurants == ["真实餐厅"]


def test_cancelling_one_restaurant_cannot_clear_unmentioned_restaurant():
    old = requirements(required_restaurants=["真实餐厅甲", "真实餐厅乙"]).model_dump()
    proposed = requirements()
    text = "取消真实餐厅甲"
    anchors.preserve_anchors(
        old,
        proposed,
        [AnchorChange(target="restaurant", action="clear", name="", user_quote=text)],
        text,
    )
    assert "真实餐厅乙" in proposed.required_restaurants


@pytest.mark.parametrize("target,name", [("hotel", "真实酒店"), ("restaurant", "真实餐厅")])
def test_explicit_named_cancellation_remains_possible(target, name):
    old = requirements(required_hotel="真实酒店", required_restaurants=["真实餐厅"]).model_dump()
    proposed = requirements()
    text = "取消" + name
    anchors.preserve_anchors(
        old,
        proposed,
        [AnchorChange(target=target, action="clear", name=name, user_quote=text)],
        text,
    )
    if target == "hotel":
        assert not proposed.required_hotel and proposed.required_restaurants == ["真实餐厅"]
    else:
        assert proposed.required_hotel == "真实酒店" and not proposed.required_restaurants


@pytest.mark.asyncio
async def test_negated_cancellation_fragment_cannot_publish_different_hotel(monkeypatch, db):
    setup(monkeypatch, req=requirements(required_hotel="真实酒店"))
    first = await orchestrator.TripOrchestrator().plan_trip(
        "negated-release", "已订真实酒店别换", interaction_mode="automatic"
    )
    assert first["status"] == "completed"
    plan = candidate()
    plan["hotel_evidence_id"] = "h2"
    setup(monkeypatch, req=requirements(pace="relaxed"), intent="modify_itinerary", plan=plan)
    physical = research.execute_search

    async def search(category, args, remaining):
        found, events, count = await physical(category, args, remaining)
        if args.get("category", category) == "hotel" and found:
            alt = deepcopy(found[0])
            alt["evidence_id"] = "h2"
            alt["data"].update(id="h2", name="其他酒店")
            found.append(alt)
        return found, events, count

    monkeypatch.setattr(research, "execute_search", search)
    understanding = pipeline.ask_json

    async def ask(schema, instruction, context):
        result, usage = await understanding(schema, instruction, context)
        if schema is RequestDecision:
            result.anchor_changes = [
                AnchorChange(
                    target="hotel", action="clear", name="真实酒店", user_quote="取消真实酒店"
                )
            ]
        return result, usage

    monkeypatch.setattr(pipeline, "ask_json", ask)
    out = await orchestrator.TripOrchestrator().plan_trip(
        "negated-release",
        "不要取消真实酒店，第二天轻松一点，其他不动",
        interaction_mode="automatic",
    )
    assert (
        out["status"] not in ("completed", "degraded")
        or out["itinerary"]["hotel_evidence_id"] == "h1"
    )


def test_cancel_patch_cannot_target_a_different_restaurant_than_quote():
    old = requirements(required_restaurants=["真实餐厅甲", "真实餐厅乙"]).model_dump()
    proposed = requirements()
    text = "取消真实餐厅甲"
    anchors.preserve_anchors(
        old,
        proposed,
        [AnchorChange(target="restaurant", action="clear", name="真实餐厅乙", user_quote=text)],
        text,
    )
    assert "真实餐厅乙" in proposed.required_restaurants


@pytest.mark.parametrize(
    "text", ["取消真实酒店？先别操作，我只是问问", "取消真实酒店，但仍然保留真实酒店"]
)
def test_question_or_conflicting_retention_does_not_release(text):
    old = requirements(required_hotel="真实酒店").model_dump()
    req = requirements()
    questions = anchors.preserve_anchors(
        old,
        req,
        [AnchorChange(target="hotel", action="clear", name="真实酒店", user_quote="取消真实酒店")],
        text,
    )
    assert req.required_hotel == "真实酒店"
    assert questions


def test_restaurant_action_cannot_replace_hotel():
    old = requirements(required_hotel="真实酒店", required_restaurants=["原餐厅"]).model_dump()
    req = requirements()
    text = "餐厅换成湖畔饭店"
    anchors.preserve_anchors(
        old,
        req,
        [AnchorChange(target="hotel", action="set", name="湖畔饭店", user_quote=text)],
        text,
    )
    assert req.required_hotel == "真实酒店"


def test_question_new_trip_does_not_reset():
    old = requirements(required_hotel="真实酒店", required_restaurants=["真实餐厅"]).model_dump()
    req = requirements()
    text = "开始新旅行？不是，继续原来的行程"
    anchors.preserve_anchors(old, req, [], text, "开始新旅行")
    assert req.required_hotel == "真实酒店" and req.required_restaurants == ["真实餐厅"]


@pytest.mark.parametrize("kind", ["clear", "replace", "new_trip", "all_restaurants"])
def test_supported_normal_changes(kind):
    old = requirements(
        required_hotel="真实酒店", required_restaurants=["真实餐厅甲", "真实餐厅乙"]
    ).model_dump()
    req = requirements()
    if kind == "clear":
        text = "请取消真实酒店"
        changes = [AnchorChange(target="hotel", action="clear", name="真实酒店", user_quote=text)]
        reset = ""
    elif kind == "replace":
        text = "酒店换成新的酒店"
        changes = [AnchorChange(target="hotel", action="set", name="新的酒店", user_quote=text)]
        reset = ""
    elif kind == "new_trip":
        text = "开始一趟新的旅行"
        changes = []
        reset = text
    else:
        text = "取消所有指定餐厅"
        changes = [AnchorChange(target="restaurant", action="clear", name="", user_quote=text)]
        reset = ""
    questions = anchors.preserve_anchors(old, req, changes, text, reset)
    assert not questions
    if kind == "replace":
        assert req.required_hotel == "新的酒店"
    elif kind == "all_restaurants":
        assert req.required_hotel == "真实酒店" and not req.required_restaurants
    elif kind == "new_trip":
        assert not req.required_hotel and not req.required_restaurants
    else:
        assert not req.required_hotel and req.required_restaurants == old["required_restaurants"]


@pytest.mark.asyncio
async def test_question_fragment_cannot_publish_different_hotel(monkeypatch, db):
    setup(monkeypatch, req=requirements(required_hotel="真实酒店"))
    first = await orchestrator.TripOrchestrator().plan_trip(
        "question-release", "已订真实酒店别换", interaction_mode="automatic"
    )
    assert first["status"] == "completed"
    plan = candidate()
    plan["hotel_evidence_id"] = "h2"
    setup(monkeypatch, req=requirements(pace="relaxed"), intent="modify_itinerary", plan=plan)
    physical = research.execute_search

    async def search(category, args, remaining):
        found, events, count = await physical(category, args, remaining)
        if args.get("category", category) == "hotel" and found:
            alt = deepcopy(found[0])
            alt["evidence_id"] = "h2"
            alt["data"].update(id="h2", name="其他酒店")
            found.append(alt)
        return found, events, count

    monkeypatch.setattr(research, "execute_search", search)
    understanding = pipeline.ask_json

    async def ask(schema, instruction, context):
        result, usage = await understanding(schema, instruction, context)
        if schema is RequestDecision:
            result.anchor_changes = [
                AnchorChange(
                    target="hotel", action="clear", name="真实酒店", user_quote="取消真实酒店"
                )
            ]
        return result, usage

    monkeypatch.setattr(pipeline, "ask_json", ask)
    out = await orchestrator.TripOrchestrator().plan_trip(
        "question-release", "取消真实酒店？先别操作，我只是问问", interaction_mode="automatic"
    )
    assert (
        out["status"] not in ("completed", "degraded")
        or out["itinerary"]["hotel_evidence_id"] == "h1"
    )
