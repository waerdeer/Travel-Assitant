"""Behavior at the human decision boundary, including real SQLite recovery."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from langchain_core.messages import HumanMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_closed_loop import candidate, evidence, install_graph, requirements

from app.graph import choices, pipeline, research
from app.schemas.planning import ChoiceSelection, HotelRevision, Itinerary, RequestDecision


def state():
    return {
        "messages": [HumanMessage(content="杭州两天")],
        "trace": [],
        "metrics": {},
        "repair_count": 0,
        "interaction_mode": "guided",
    }


def selected(pending):
    return ChoiceSelection(
        token=pending["token"],
        hotel_evidence_id=pending["hotels"][0]["evidence_id"],
        restaurant_evidence_ids=[pending["restaurants"][0]["evidence_id"]],
    )


@pytest.mark.parametrize("automatic", [False, True])
async def test_guided_graph_pauses_before_planning_then_resumes_without_understanding(
    monkeypatch, automatic
):
    graph, calls = install_graph(monkeypatch)
    paused = await graph.ainvoke(state())
    assert paused["status"] == "awaiting_choice"
    assert not paused.get("itinerary")
    assert [schema for schema, _ in calls] == ["RequestDecision"]
    decision = (
        ChoiceSelection(token=paused["pending_choice"]["token"], automatic=True)
        if automatic
        else selected(paused["pending_choice"])
    )
    resumed = await graph.ainvoke(
        {
            **paused,
            "choice_selection": decision.model_dump(),
            "trace": [],
            "metrics": {},
            "tool_calls": 0,
        }
    )
    assert resumed["status"] == "completed"
    assert resumed["pending_choice"] is None
    assert [schema for schema, _ in calls] == ["RequestDecision", "Itinerary"]
    assert resumed["selected_options"] == (
        {} if automatic else {"hotel_evidence_id": "h1", "restaurant_evidence_ids": ["r1"]}
    )


async def test_durable_pause_history_resume_and_duplicate_rejection(monkeypatch, tmp_path):
    from app.agents import orchestrator
    from app.db.base import Base
    from app.db.database import get_session
    from app.db.models import AgentCheckpoint, Message
    from app.main import app

    graph, calls = install_graph(monkeypatch)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'choices.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(orchestrator, "async_session_factory", factory)
    monkeypatch.setattr(orchestrator, "app_graph", graph)

    async def sessions():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    try:
        first = await orchestrator.TripOrchestrator().plan_trip(
            "human-case", "杭州两天", interaction_mode="guided", planning_strategy="legacy"
        )
        assert first["persisted"] and first["status"] == "awaiting_choice"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            history = (await client.get("/api/v1/conversations/human-case")).json()
            assert history["pending_choice"]["token"] == first["pending_choice"]["token"]
            assert history["last_run"]["metrics"]["model_calls"] == 1
        decision = selected(history["pending_choice"])
        second = await orchestrator.TripOrchestrator().plan_trip(
            "human-case", "ignored", selection=decision, interaction_mode="guided"
        )
        assert second["status"] == "completed" and second["persisted"]
        before = len(calls)
        with pytest.raises(choices.ChoiceConflict, match="已失效"):
            await orchestrator.TripOrchestrator().plan_trip("human-case", "", selection=decision)
        assert len(calls) == before
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            duplicate = await client.post(
                "/api/v1/chat_plan",
                json={"thread_id": "human-case", "selection": decision.model_dump()},
            )
            assert duplicate.status_code == 409
            streamed = await client.post(
                "/api/v1/chat_plan/stream",
                json={"thread_id": "human-case", "selection": decision.model_dump()},
            )
            assert "event: error" in streamed.text and "event: result" not in streamed.text
        assert len(calls) == before
        async with factory() as session:
            checkpoint = await session.get(AgentCheckpoint, "human-case")
            assert checkpoint.state_json["pending_choice"] is None
            assert await session.scalar(select(func.count()).select_from(Message)) == 4
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def pending_state():
    base = {
        "requirements": requirements().model_dump(),
        "intent": "modify_hotel",
        "evidence": [e.model_dump() for e in evidence()],
        "review_categories": ["hotel", "restaurant"],
        "interaction_mode": "guided",
        "scope_policy_version": choices.SCOPE_POLICY_VERSION,
        "trace": [],
    }
    return {**base, **await choices.review_options(base)}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: setattr(s, "token", "old-token"),
        lambda s: setattr(s, "hotel_evidence_id", "invented"),
        lambda s: setattr(s, "restaurant_evidence_ids", ["invented"]),
        lambda s: setattr(s, "restaurant_evidence_ids", ["r1", "r1"]),
        lambda s: setattr(s, "automatic", True),
    ],
)
async def test_invalid_or_conflicting_choices_never_enter_planning(mutation):
    paused = await pending_state()
    decision = selected(paused["pending_choice"])
    mutation(decision)
    with pytest.raises(choices.ChoiceConflict):
        choices.validate_selection(paused, decision)


async def test_expired_candidates_require_refresh():
    paused = await pending_state()
    decision = selected(paused["pending_choice"])
    paused["pending_choice"]["hotels"][0]["fetched_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=7)
    ).isoformat()
    with pytest.raises(choices.ChoiceConflict, match="过期"):
        choices.validate_selection(paused, decision)


async def test_hotel_resume_restores_original_intent_and_itinerary_after_chat(monkeypatch):
    paused = await pending_state()
    paused.update(intent="chat", previous_itinerary=None, accepted_plan={"itinerary": candidate()})
    resumed = await choices.apply_selection(
        {**paused, "choice_selection": selected(paused["pending_choice"]).model_dump()}
    )
    assert resumed["intent"] == "modify_hotel"
    assert resumed["previous_itinerary"] == candidate()

    async def ask(schema, instruction, context):
        assert schema is HotelRevision
        return HotelRevision(hotel_evidence_id="h1", accommodation=150, basis="仅修改住宿估算"), {
            "model_calls": 1
        }

    monkeypatch.setattr(pipeline, "ask_json", ask)
    output = await pipeline.plan(
        {**paused, **resumed, "messages": [HumanMessage(content="选好了")]}
    )
    assert (
        output["itinerary"]["days"]
        == Itinerary.model_validate(candidate()).model_dump(mode="json")["days"]
    )
    for key in ("meals", "transport", "tickets"):
        assert output["itinerary"]["costs"][key] == candidate()["costs"][key]


def test_shortlist_round_robins_search_directions_and_deduplicates_branches():
    base = evidence()[-1].model_dump()
    items = []
    for ref, name, hint in [
        ("h1", "同一酒店(甲店)", "中档"),
        ("h2", "同一酒店(乙店)", "中档"),
        ("h3", "湖边民宿", "民宿"),
        ("h4", "其他酒店", "中档"),
    ]:
        item = deepcopy(base)
        item.update(evidence_id=ref)
        item["data"].update(name=name, retrieval_hint=hint)
        items.append(item)
    result = choices.shortlist(items, "hotel", 3)
    assert [r["evidence_id"] for r in result] == ["h1", "h3", "h4"]


async def test_selected_hotel_is_a_constraint_even_if_model_chooses_other_evidence():
    places = [e.model_dump() for e in evidence()]
    other = deepcopy(places[-1])
    other["evidence_id"] = "h2"
    places.append(other)
    plan = candidate()
    plan["hotel_evidence_id"] = "h2"
    result = await pipeline.validate(
        {
            "requirements": requirements().model_dump(),
            "evidence": places,
            "itinerary": plan,
            "selected_options": {"hotel_evidence_id": "h1"},
            "trace": [],
            "repair_count": 1,
        }
    )
    assert not result["validation"]["passed"]
    assert "invalid_hotel" in {issue["code"] for issue in result["validation"]["issues"]}


async def test_spatial_repair_returns_to_user_instead_of_silently_replacing_choice():
    paused = await pending_state()
    paused.update(choice_confirmed=True, validation={"issues": [{"code": "long_transfer"}]})
    output = await choices.review_options(paused)
    assert output["status"] == "awaiting_choice"
    assert not output["pending_choice"]["hotels"]
    assert "重新选择" in output["reply"]


async def test_diverse_queries_share_the_physical_tool_budget(monkeypatch):
    calls = []

    async def search(category, args, remaining):
        calls.append((category, args))
        return [], [], 1

    monkeypatch.setattr(research, "execute_search", search)
    base = [e.model_dump() for e in evidence() if e.category == "attraction"]
    result = await research.collect_evidence(
        {
            "requirements": requirements().model_dump(),
            "evidence": base,
            "decision": {
                "hotel_profiles": ["中档", "民宿"],
                "food_queries": ["本地菜", "小吃", "面馆"],
            },
        }
    )
    assert len([c for c in calls if c[0] == "hotel"]) == 2
    assert len([c for c in calls if c[0] == "restaurant"]) == 3
    assert result["tool_calls"] == len(calls) == 6


async def test_later_hotel_edit_only_reopens_hotel_choice(monkeypatch):
    async def ask(schema, instruction, context):
        return RequestDecision(intent="modify_hotel", requirements=requirements()), {
            "model_calls": 1
        }

    monkeypatch.setattr(pipeline, "ask_json", ask)
    output = await pipeline.understand(
        {
            "messages": [HumanMessage(content="换酒店，餐厅不改")],
            "requirements": requirements().model_dump(),
            "evidence": [e.model_dump() for e in evidence()],
            "accepted_plan": {"itinerary": candidate()},
            "choice_confirmed": True,
            "selected_options": {"hotel_evidence_id": "h1", "restaurant_evidence_ids": ["r1"]},
        }
    )
    assert output["review_categories"] == ["hotel"]
    assert output["selected_options"] == {"restaurant_evidence_ids": ["r1"]}


async def test_changing_to_a_single_day_releases_the_previous_hotel_choice(monkeypatch):
    req = requirements().model_copy(update={"end_date": "2026-11-01", "duration_days": 1})

    async def ask(schema, instruction, context):
        return RequestDecision(intent="modify_itinerary", requirements=req), {"model_calls": 1}

    monkeypatch.setattr(pipeline, "ask_json", ask)
    output = await pipeline.understand(
        {
            "messages": [HumanMessage(content="改为一天，当天返回")],
            "requirements": requirements().model_dump(),
            "evidence": [e.model_dump() for e in evidence()],
            "accepted_plan": {"itinerary": candidate()},
            "choice_confirmed": True,
            "selected_options": {"hotel_evidence_id": "h1"},
        }
    )
    assert "hotel_evidence_id" not in output["selected_options"]
    assert not any(e["category"] == "hotel" for e in output["evidence"])


async def test_refreshed_evidence_missing_a_selected_hotel_reopens_only_that_choice():
    base = await pending_state()
    base.update(
        choice_confirmed=True,
        review_categories=[],
        selected_options={"hotel_evidence_id": "old-hotel"},
    )
    output = await choices.review_options(base)
    assert output["status"] == "awaiting_choice"
    assert output["pending_choice"]["hotels"]
    assert not output["pending_choice"]["restaurants"]


async def test_missing_selected_evidence_with_no_replacements_blocks_instead_of_ignoring_choice():
    base = await pending_state()
    base.update(
        choice_confirmed=True,
        review_categories=[],
        selected_options={"hotel_evidence_id": "old-hotel"},
    )
    base["evidence"] = [e for e in base["evidence"] if e["category"] != "hotel"]
    output = await choices.review_options(base)
    assert output["status"] == "blocked"
    assert choices.after_review(output) == "deliver"
    assert not output.get("itinerary")


async def test_empty_spatial_research_preserves_selected_evidence(monkeypatch):
    """Xinjiang regression: an empty nearby response is not evidence expiration."""
    base = await pending_state()
    base.update(
        decision={"food_query": "新疆菜"},
        itinerary=candidate(),
        choice_confirmed=True,
        selected_options={"hotel_evidence_id": "h1", "restaurant_evidence_ids": ["r1"]},
        validation={"passed": False, "issues": [
            {"code": "long_transfer", "severity": "error", "message": "距离过远"},
            {"code": "distant_hotel", "severity": "error", "message": "酒店过远"},
        ]},
        tool_calls=0,
    )

    async def empty(category, args, remaining):
        assert category == "nearby"
        return [], [{"stage": "tool", "tool": "nearby", "ok": True, "count": 0}], 1

    monkeypatch.setattr(research, "execute_search", empty)
    result = await research.collect_evidence(base)
    assert {"h1", "r1"} <= {e["evidence_id"] for e in result["evidence"]}
    reviewed = await choices.review_options({**base, **result})
    assert reviewed["status"] == "awaiting_choice"
    assert reviewed["pending_choice"]["selected_options"] == base["selected_options"]
    assert "没有找到新的可用候选" in reviewed["reply"]
    assert reviewed["pending_choice"]["no_progress"]


async def test_region_scope_clarifies_before_any_research(monkeypatch):
    decision = RequestDecision(
        intent="new_trip", requirements=requirements(),
        scope_clarification="北疆跨度大，目前请先选择一个集中游玩的区域，或拆成分段行程。",
    )
    graph, calls = install_graph(monkeypatch, decision=decision)
    result = await graph.ainvoke({**state(), "messages": [HumanMessage(content="去北疆高级奢华游 下周一整周")]})
    assert result["status"] == "awaiting_clarification"
    assert "北疆跨度大" in result["reply"]
    assert not any(e["stage"] == "research" for e in result["trace"])
    assert [name for name, _ in calls] == ["RequestDecision"]


async def test_legacy_construction_hotel_cannot_be_selected_or_planned():
    base = await pending_state()
    option = base["pending_choice"]["hotels"][0]
    option["name"] = "喀纳斯禾木英迪格酒店(建设中)"
    decision = selected(base["pending_choice"])
    with pytest.raises(choices.ChoiceConflict, match="建设"):
        choices.validate_selection(base, decision)
    for e in base["evidence"]:
        if e["evidence_id"] == option["evidence_id"]:
            e["data"]["name"] = option["name"]
    assert choices.shortlist(base["evidence"], "hotel", 4) == []
    assert not any(e["category"] == "hotel" for e in choices.planner_evidence(base))
    assert not any(e["category"] == "hotel" for e in research.fresh_evidence(base["evidence"], "杭州市"))


async def test_spatial_review_keeps_chosen_option_visible_even_after_many_alternatives():
    base = await pending_state()
    originals = deepcopy(base["evidence"])
    alternatives = []
    for index in range(10):
        item = deepcopy(next(e for e in originals if e["category"] == "hotel"))
        item["evidence_id"] = f"other-{index}"
        item["data"]["name"] = f"附近酒店{index}"
        alternatives.append(item)
    base.update(
        evidence=alternatives + originals,
        choice_confirmed=True,
        selected_options={"hotel_evidence_id": "h1", "restaurant_evidence_ids": ["r1"]},
        validation={"issues": [{"code": "distant_hotel"}]},
    )
    result = await choices.review_options(base)
    assert result["pending_choice"]["hotels"][0]["evidence_id"] == "h1"
