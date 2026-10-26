"""On-demand plan, real graph/SQLite/API and read-only discovery boundaries."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from test_closed_loop import candidate, evidence, requirements
from test_route_first import db as db
from test_route_first import setup

from app.agents import orchestrator
from app.db.database import get_session
from app.db.models import AgentCheckpoint, Message, Trip
from app.graph import choices, tools
from app.graph.rendering import render_plan
from app.graph.validation import validate_itinerary
from app.main import app
from app.schemas.planning import Itinerary
from app.services.images import poi_images


def flexible_plan():
    plan = candidate()
    plan["service_mode"] = "browse"
    plan["hotel_evidence_id"] = None
    for index, day in enumerate(plan["days"]):
        day["stops"] = day["stops"][:1]
        ref = day["stops"][0]["evidence_id"]
        day["meal_breaks"] = [
            {"anchor_evidence_id": ref, "start_time": "12:00", "end_time": "13:00"}
        ]
        if index == 0:
            day["stay_anchor_evidence_id"] = ref
    return plan


def test_available_candidates_do_not_force_specific_service_references():
    plan = Itinerary.model_validate(flexible_plan())
    report = validate_itinerary(plan, requirements(), evidence())
    assert report.passed
    markdown = render_plan(plan, requirements(), evidence(), report)
    assert "自由用餐" in markdown and "住宿建议区域" in markdown
    assert "真实酒店" not in markdown and "真实餐厅" not in markdown


def test_flexible_meal_and_visits_render_in_time_order():
    data = flexible_plan()
    data["days"][0]["stops"].append(
        {"evidence_id": "a2", "start_time": "16:00", "end_time": "18:00"}
    )
    plan = Itinerary.model_validate(data)
    report = validate_itinerary(plan, requirements(), evidence())
    text = render_plan(plan, requirements(), evidence(), report)
    assert text.index("09:00") < text.index("12:00") < text.index("16:00")


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda p: p["days"][0].pop("stay_anchor_evidence_id"), "missing_stay_area"),
        (lambda p: p["days"][0].update(stay_anchor_evidence_id="a2"), "invalid_stay_anchor"),
        (
            lambda p: p["days"][0]["meal_breaks"][0].update(anchor_evidence_id="a2"),
            "invalid_meal_anchor",
        ),
        (lambda p: p["days"][0]["meal_breaks"][0].update(start_time="10:00"), "meal_time_overlap"),
        (lambda p: p["costs"].update(meals=0), "missing_costs"),
    ],
)
def test_flexible_still_enforces_real_anchors_schedule_and_budget(change, code):
    data = flexible_plan()
    change(data)
    report = validate_itinerary(Itinerary.model_validate(data), requirements(), evidence())
    assert not report.passed and code in {issue.code for issue in report.issues}


def test_locked_meal_pool_cannot_be_replaced_by_free_meals():
    state = {
        "requirements": requirements().model_dump(),
        "evidence": [e.model_dump() for e in evidence()],
        "selected_options": {"restaurant_evidence_ids": ["r1"]},
    }
    assert "selected_daily_restaurant_missing" in {
        i.code for i in choices.selected_constraint_issues(state, flexible_plan())
    }


async def test_default_completes_without_preselecting_or_researching_ordinary_services(
    monkeypatch, db
):
    _, calls = setup(monkeypatch)
    result = await orchestrator.TripOrchestrator().plan_trip("default-browse", "杭州两天")
    assert (
        result["status"] == "completed" and result["persisted"] and not result.get("pending_choice")
    )
    assert (
        result["itinerary"]["service_mode"] == "browse"
        and not result["itinerary"]["hotel_evidence_id"]
    )
    assert result["itinerary"]["days"][0]["stay_anchor_evidence_id"]
    assert not any(name in ("hotel", "restaurant", "nearby") for name, _ in calls)


@pytest.fixture
async def client(db):
    async def override():
        async with db() as session:
            yield session

    app.dependency_overrides[get_session] = override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


async def seed(monkeypatch, client):
    setup(monkeypatch)
    result = (
        await client.post("/api/v1/chat_plan", json={"thread_id": "browse", "text": "杭州两天"})
    ).json()
    assert result["status"] == "completed"
    trip = (await client.get("/api/v1/conversations/browse/trip")).json()
    assert trip["version"] == result["plan"]["version"]
    return {
        "plan_version": trip["version"],
        "date": "2026-11-01",
        "anchor_evidence_id": "a1",
        "category": "hotel",
    }


def source(monkeypatch, *, empty=False, failed=False):
    calls = []

    async def call(tool, args):
        calls.append((tool, args))
        if failed:
            raise ConnectionError()
        pois = (
            []
            if empty
            else [
                {
                    "id": "h-new",
                    "name": "湖畔酒店",
                    "address": "湖滨",
                    "typecode": "100000",
                    "location": "120.14,30.24",
                    "photos": [{"url": "https://images.example.com/real-poi.jpg"}],
                },
                {
                    "id": "r-new",
                    "name": "特色餐厅",
                    "address": "湖滨",
                    "typecode": "050000",
                    "location": "120.14,30.24",
                },
                {
                    "id": "closed",
                    "name": "停业酒店",
                    "address": "湖滨",
                    "typecode": "100000",
                    "business_status": "closed",
                },
                {
                    "id": "other-city",
                    "name": "异城酒店",
                    "address": "成都",
                    "typecode": "100000",
                    "cityname": "成都市",
                },
                {
                    "id": "far",
                    "name": "远处酒店",
                    "address": "市内远处",
                    "typecode": "100000",
                    "location": "119.5,30.24",
                },
            ]
        )
        return SimpleNamespace(success=True, content=[{"pois": pois}]), None

    monkeypatch.setattr(tools, "_call_mcp", call)
    return calls


async def snapshot(db):
    async with db() as session:
        trip = (await session.execute(select(Trip))).scalar_one()
        checkpoint = (await session.execute(select(AgentCheckpoint))).scalar_one()
        messages = (await session.execute(select(Message))).scalars().all()
        return deepcopy(
            (
                trip.plan_json,
                trip.plan_md,
                checkpoint.state_json,
                [(m.id, m.content) for m in messages],
            )
        )


async def test_browse_is_read_only_sourced_and_version_bound(monkeypatch, client, db):
    request = await seed(monkeypatch, client)
    calls = source(monkeypatch)
    before = await snapshot(db)
    response = await client.post("/api/v1/conversations/browse/browse", json=request)
    assert response.status_code == 200
    result = response.json()
    assert [item["poi_id"] for item in result["items"]] == ["h-new"]
    assert result["items"][0]["images"][0]["poi_id"] == "h-new"
    assert all(args["location"] == "120.14,30.24" for _, args in calls)
    assert await snapshot(db) == before
    calls.clear()
    response = await client.post(
        "/api/v1/conversations/browse/browse", json={**request, "plan_version": "0" * 64}
    )
    assert response.status_code == 409 and not calls


@pytest.mark.parametrize(
    "changes",
    [
        {"date": "2026-12-01"},
        {"anchor_evidence_id": "a2"},
        {"category": "hotel", "date": "2026-11-02"},
        {"location": "1,2"},
    ],
)
async def test_invalid_browse_context_never_reaches_maps(monkeypatch, client, changes):
    request = await seed(monkeypatch, client)
    calls = source(monkeypatch)
    response = await client.post("/api/v1/conversations/browse/browse", json={**request, **changes})
    assert response.status_code in (400, 422) and not calls


@pytest.mark.parametrize("failed,expected", [(False, 200), (True, 502)])
async def test_empty_is_distinct_from_unavailable_and_plan_preserved(
    monkeypatch, client, db, failed, expected
):
    request = await seed(monkeypatch, client)
    source(monkeypatch, empty=True, failed=failed)
    before = await snapshot(db)
    response = await client.post("/api/v1/conversations/browse/browse", json=request)
    assert response.status_code == expected
    if not failed:
        assert response.json()["items"] == []
    assert await snapshot(db) == before


async def test_new_version_during_network_call_discards_old_browse(monkeypatch, client, db):
    request = await seed(monkeypatch, client)
    started = asyncio.Event()
    release = asyncio.Event()

    async def call(tool, args):
        started.set()
        await release.wait()
        return SimpleNamespace(success=True, content=[{"pois": []}]), None

    monkeypatch.setattr(tools, "_call_mcp", call)
    task = asyncio.create_task(client.post("/api/v1/conversations/browse/browse", json=request))
    await started.wait()
    async with db() as session:
        trip = (await session.execute(select(Trip))).scalar_one()
        data = deepcopy(trip.plan_json)
        data["itinerary"]["days"][0]["theme"] = "新版本"
        trip.plan_json = data
        await session.commit()
    release.set()
    assert (await task).status_code == 409


@pytest.mark.parametrize(
    "raw",
    [
        {"photos": None},
        {"photos": [None, {}, [], {"url": 5}]},
        {"photo": "javascript:alert(1)"},
        {"photo": "http://127.0.0.1/x"},
        {"photo": "https://user:pass@example.com/a"},
    ],
)
def test_invalid_photo_input_is_optional_not_a_failure(raw):
    assert poi_images(raw) == []


@pytest.mark.parametrize(
    "gap,code,severity",
    [(30, "long_attraction_transfer", "error"), (180, "long_transfer_unverified", "warning")],
)
def test_cross_area_visits_distinguish_insufficient_and_ample_transfer_time(gap, code, severity):
    from app.graph.pipeline import after_validate

    data = flexible_plan()
    data["days"] = data["days"][:1]
    second_start = 10 * 60 + gap
    data["days"][0]["stops"] = [
        {"evidence_id": "a1", "start_time": "09:00", "end_time": "10:00"},
        {
            "evidence_id": "a2",
            "start_time": f"{second_start // 60:02d}:{second_start % 60:02d}",
            "end_time": f"{second_start // 60 + 1:02d}:{second_start % 60:02d}",
        },
    ]
    data["days"][0]["meal_breaks"] = [
        {"anchor_evidence_id": "a2", "start_time": "15:00", "end_time": "16:00"}
    ]
    facts = evidence()
    facts[1].data["location"] = "120.60,30.24"
    req = requirements()
    req.end_date = req.start_date
    report = validate_itinerary(Itinerary.model_validate(data), req, facts)
    assert any(issue.code == code and issue.severity == severity for issue in report.issues)
    if severity == "error":
        state = {
            "validation": report.model_dump(),
            "repair_count": 1,
            "interaction_mode": "guided",
            "research_round": 0,
            "tool_calls": 0,
            "requirements": req.model_dump(),
        }
        assert after_validate(state) == "plan"
    else:
        assert report.passed


def test_distant_hotel_is_specific_commute_warning_and_remains_selected():
    data = candidate()
    facts = evidence()
    facts[3].data["location"] = "120.90,30.24"
    report = validate_itinerary(
        Itinerary.model_validate(data), requirements(required_hotel="真实酒店"), facts
    )
    assert report.passed
    warnings = [issue for issue in report.issues if issue.code == "distant_hotel"]
    assert warnings and all(
        issue.severity == "warning" and "真实酒店" in issue.message and issue.day
        for issue in warnings
    )
    assert data["hotel_evidence_id"] == "h1"


def test_meal_at_same_anchor_can_start_without_fake_transport_gap():
    data = flexible_plan()
    data["days"][0]["meal_breaks"][0].update(start_time="11:00", end_time="12:00")
    assert validate_itinerary(Itinerary.model_validate(data), requirements(), evidence()).passed


async def test_text_planner_context_does_not_duplicate_facts_or_include_photo_assets(
    monkeypatch, db
):
    from app.graph import research

    _, calls = setup(monkeypatch)
    physical = research.execute_search

    async def search(category, args, remaining):
        facts, trace, count = await physical(category, args, remaining)
        for fact in facts:
            fact["data"]["image_urls"] = ["https://images.example.com/poi.jpg"]
        return facts, trace, count

    monkeypatch.setattr(research, "execute_search", search)
    result = await orchestrator.TripOrchestrator().plan_trip("asset-context", "杭州两天")
    assert result["status"] == "completed" and any(
        e["data"].get("image_urls") for e in result["evidence"]
    )
    for name, context in calls:
        if name in ("RouteDraft", "Itinerary"):
            assert all("image_urls" not in fact["data"] for fact in context["evidence"])
        if name == "Itinerary":
            assert "evidence" not in context["route_draft"]
