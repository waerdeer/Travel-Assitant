"""Behavioral regression suite: real graph + real SQLite, deterministic model/tool doubles."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.graph import pipeline, research, workflow
from app.graph.validation import requirement_problems, validate_itinerary
from app.schemas.planning import Evidence, Itinerary, RequestDecision, Requirements


def requirements(**changes):
    return Requirements(
        city="杭州市",
        start_date="2026-11-01",
        end_date="2026-11-02",
        budget_per_person=1000,
        **changes,
    )


def evidence():
    return [
        Evidence(
            evidence_id=ref,
            category=category,
            city="杭州市",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            data={
                "id": ref,
                "name": name,
                "address": "杭州市西湖区",
                "location": coords,
            },
        )
        for ref, category, name, coords in [
            ("a1", "attraction", "西湖", "120.14,30.24"),
            ("a2", "attraction", "浙江省博物馆", "120.13,30.25"),
            ("r1", "restaurant", "真实餐厅", "120.14,30.24"),
            ("h1", "hotel", "真实酒店", "120.14,30.24"),
        ]
    ]


def candidate():
    return {
        "city": "杭州市",
        "days": [
            {
                "date": "2026-11-01",
                "theme": "湖畔慢行",
                "stops": [
                    {"evidence_id": "a1", "start_time": "09:00", "end_time": "11:00"},
                    {"evidence_id": "r1", "start_time": "12:00", "end_time": "13:00"},
                ],
            },
            {
                "date": "2026-11-02",
                "theme": "文化漫步",
                "stops": [
                    {"evidence_id": "a2", "start_time": "09:00", "end_time": "11:00"},
                    {"evidence_id": "r1", "start_time": "12:00", "end_time": "13:00"},
                ],
            },
        ],
        "hotel_evidence_id": "h1",
        "costs": {
            "accommodation": 200,
            "meals": 160,
            "transport": 60,
            "tickets": 0,
            "basis": "住宿200×1晚，餐饮80×2天，交通30×2天；均为估算",
        },
        "suggestions": [],
    }


def report(data):
    return validate_itinerary(Itinerary.model_validate(data), requirements(), evidence())


def test_valid_sourced_itinerary_passes_with_honest_warnings():
    result = report(candidate())
    assert result.passed
    assert {i.code for i in result.issues} == {"weather_uncovered", "estimates_only"}


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda p: p.update(city="成都市"), "city_mismatch"),
        (lambda p: p["days"].pop(), "date_coverage"),
        (
            lambda p: p["days"][0]["stops"][0].update(evidence_id="invented"),
            "invalid_reference",
        ),
        (lambda p: p.update(hotel_evidence_id="a1"), "invalid_hotel"),
        (lambda p: p["days"][0]["stops"][1].update(start_time="10:30"), "time_overlap"),
        (lambda p: p["days"][0]["stops"][0].update(start_time="07:00"), "time_window"),
        (
            lambda p: p["days"][1]["stops"][0].update(evidence_id="a1"),
            "duplicate_attraction",
        ),
        (lambda p: p["costs"].update(accommodation=2000), "budget_exceeded"),
        (lambda p: p["costs"].update(accommodation=0), "missing_hotel_cost"),
        (lambda p: p["costs"].update(meals=0), "missing_costs"),
        (
            lambda p: p["days"][0]["stops"][1].update(start_time="11:05"),
            "transfer_buffer",
        ),
    ],
)
def test_constraints_reject_bad_candidates(mutation, code):
    data = candidate()
    mutation(data)
    result = report(data)
    assert not result.passed
    assert code in [i.code for i in result.issues]


def test_must_visit_and_exclusions_are_hard_constraints():
    req = requirements(must_visit=["灵隐寺"], avoid_places=["西湖"])
    result = validate_itinerary(Itinerary.model_validate(candidate()), req, evidence())
    assert {"must_visit_missing", "excluded_place"} <= {i.code for i in result.issues}


def test_missing_dates_are_not_silently_defaulted():
    assert len(requirement_problems(Requirements(city="杭州市", duration_days=3))) == 1


def install_graph(monkeypatch, candidates=None, decision=None, no_evidence=False):
    requests = []
    options = candidates or [candidate()]

    async def ask(schema, instruction, context):
        requests.append((schema.__name__, deepcopy(context)))
        if schema is RequestDecision:
            return decision or RequestDecision(intent="new_trip", requirements=requirements()), {
                "model_calls": 1
            }
        index = sum(name == "Itinerary" for name, _ in requests) - 1
        return Itinerary.model_validate(options[min(index, len(options) - 1)]), {"model_calls": 1}

    async def collect(state):
        return {
            "evidence": [] if no_evidence else [e.model_dump() for e in evidence()],
            "trace": state["trace"] + [{"stage": "research"}],
            "tool_calls": 4,
        }

    monkeypatch.setattr(pipeline, "ask_json", ask)
    monkeypatch.setattr(workflow, "collect_evidence", collect)
    return workflow.build_workflow().compile(), requests


async def invoke(graph):
    return await graph.ainvoke(
        {
            "messages": [HumanMessage(content="杭州两天")],
            "trace": [],
            "metrics": {},
            "repair_count": 0,
        }
    )


async def test_real_graph_repairs_failed_candidate_then_delivers(monkeypatch):
    bad = candidate()
    bad["costs"]["accommodation"] = 2000
    graph, requests = install_graph(monkeypatch, candidates=[bad, candidate()])
    result = await invoke(graph)
    assert result["status"] == "completed"
    assert result["repair_count"] == 2
    assert [e["passed"] for e in result["trace"] if e["stage"] == "validate"] == [
        False,
        True,
    ]
    assert requests[-1][1]["validation_feedback"]["issues"]
    assert result["accepted_plan"]["itinerary"]
    assert "真实酒店" in result["final_plan_md"]


async def test_repair_limit_never_labels_failed_plan_completed(monkeypatch):
    bad = candidate()
    bad["costs"]["accommodation"] = 2000
    graph, _ = install_graph(monkeypatch, candidates=[bad])
    result = await invoke(graph)
    assert result["status"] == "needs_revision"
    assert result["repair_count"] == 3
    assert result["final_plan_md"] == ""
    assert not result.get("accepted_plan")


async def test_clarification_avoids_all_tools_and_planning(monkeypatch):
    graph, requests = install_graph(
        monkeypatch,
        decision=RequestDecision(intent="new_trip", requirements=Requirements(city="杭州市")),
    )
    result = await invoke(graph)
    assert result["status"] == "awaiting_clarification"
    assert not any(e["stage"] == "research" for e in result["trace"])
    assert [name for name, _ in requests] == ["RequestDecision"]
    assert not result["final_plan_md"]


async def test_empty_evidence_blocks_hallucinated_plan(monkeypatch):
    graph, requests = install_graph(monkeypatch, no_evidence=True)
    result = await invoke(graph)
    assert result["status"] == "blocked"
    assert not result["final_plan_md"]
    assert [name for name, _ in requests] == ["RequestDecision"]


async def test_chat_does_not_republish_existing_trip(monkeypatch):
    graph, requests = install_graph(
        monkeypatch,
        decision=RequestDecision(intent="chat", requirements=requirements(), reply="不客气"),
    )
    state = {
        "messages": [HumanMessage(content="谢谢")],
        "itinerary": candidate(),
        "final_plan_md": "已有行程",
        "validation": {"passed": True},
        "trace": [],
        "metrics": {},
    }
    result = await graph.ainvoke(state)
    assert result["status"] == "chat"
    assert result["reply"] == "不客气"
    assert result["validation"] == {}  # Ordinary chat does not run itinerary checks.
    assert [name for name, _ in requests] == ["RequestDecision"]


async def test_follow_up_uses_accepted_facts_after_a_failed_edit(monkeypatch):
    graph, requests = install_graph(
        monkeypatch,
        decision=RequestDecision(intent="chat", requirements=requirements(), reply="仍需核实预约"),
    )
    accepted = {
        "itinerary": candidate(),
        "requirements": requirements().model_dump(),
        "evidence": [e.model_dump() for e in evidence()],
        "validation": report(candidate()).model_dump(),
    }
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="之前的行程能直接出发了吗？")],
            "requirements": {"city": "成都市"},
            "status": "needs_revision",
            "itinerary": None,
            "accepted_plan": accepted,
            "validation": {"passed": False},
            "trace": [],
            "metrics": {},
        }
    )
    facts = requests[0][1]["accepted_plan_summary"]
    assert facts["requirements"]["city"] == "杭州市"
    assert facts["days"][0]["places"] == ["西湖", "真实餐厅"]
    assert facts["hotel_candidate"] == "真实酒店"
    assert facts["validation"]["passed"] is True
    assert facts["limitations"]
    assert result["accepted_plan"] == accepted
    assert result["status"] == "chat"
    assert len(requests) == 1


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"ok": False, "error": {"retryable": False, "code": "auth"}}, 1),
        ({"ok": False, "error": {"retryable": True, "code": "timeout"}}, 2),
        ({"ok": True, "items": []}, 2),
    ],
)
async def test_executor_enforces_retry_budget(monkeypatch, payload, expected):
    import json

    calls = []

    class Tool:
        name = "test_tool"

        async def ainvoke(self, args):
            calls.append(args)
            return json.dumps(payload)

    monkeypatch.setitem(research.TOOLS, "attraction", Tool())
    found, trace, count = await research.execute_search(
        "attraction", {"city": "杭州市", "keywords": "摄影"}, 10
    )
    assert count == len(calls) == len(trace) == expected
    assert not found


async def test_tool_budget_is_a_physical_call_limit(monkeypatch):
    import json

    class Tool:
        name = "test_tool"

        async def ainvoke(self, args):
            return json.dumps({"ok": True, "items": []})

    monkeypatch.setitem(research.TOOLS, "attraction", Tool())
    _, _, count = await research.execute_search(
        "attraction", {"city": "杭州市", "keywords": "摄影"}, 1
    )
    assert count == 1


async def test_restart_restores_state_and_chat_never_overwrites_trip(monkeypatch, tmp_path):
    from sqlalchemy import select

    from app.agents import orchestrator
    from app.db.base import Base
    from app.db.models import Trip

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'restore.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(orchestrator, "async_session_factory", factory)
    graph, _ = install_graph(monkeypatch)
    monkeypatch.setattr(orchestrator, "app_graph", graph)
    try:
        first = await orchestrator.TripOrchestrator().plan_trip(
            "restore-test", "杭州两天", interaction_mode="automatic", planning_strategy="legacy"
        )
        assert first["persisted"]
        graph, requests = install_graph(
            monkeypatch,
            decision=RequestDecision(intent="chat", requirements=requirements(), reply="不客气"),
        )
        monkeypatch.setattr(orchestrator, "app_graph", graph)
        second = await orchestrator.TripOrchestrator().plan_trip("restore-test", "谢谢")
        assert second["status"] == "chat"
        assert requests[0][1]["previous_requirements"]["city"] == "杭州市"
        assert len(second["messages"]) == 4
        async with factory() as session:
            trip = (await session.execute(select(Trip))).scalar_one()
            assert trip.plan_md == first["final_plan_md"]
    finally:
        await engine.dispose()
