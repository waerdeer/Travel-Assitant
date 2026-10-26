"""Availability is checked independently of model prose and empty-day claims."""

import pytest
from langchain_core.messages import HumanMessage
from test_closed_loop import candidate, evidence, requirements
from test_route_first import db as db
from test_route_first import initial, setup

from app.agents.orchestrator import TripOrchestrator
from app.graph import pipeline
from app.graph.drafts import check_draft, requirements_key
from app.graph.rendering import render_plan
from app.graph.schedule import day_schedule, preserve_schedule
from app.graph.validation import requirement_problems, validate_itinerary
from app.schemas.planning import Itinerary, RequestDecision, Requirements


def empty_plan():
    data = candidate()
    data.update(service_mode="browse", hotel_evidence_id=None)
    for day in data["days"]:
        day["stops"] = []
        day["theme"] = "入住休息或返程"
    return data


def report(data, req):
    return validate_itinerary(Itinerary.model_validate(data), req, evidence())


def codes(result):
    return {issue.code for issue in result.issues if issue.severity == "error"}


def test_original_counterexample_fails_despite_valid_ids_and_budget():
    req = requirements(arrival_time="19:00", departure_time="10:00", rest_dates=["2026-11-01"])
    result = report(candidate(), req)
    assert not result.passed
    assert {"availability_window", "rest_day_activity"} <= codes(result)


def test_arrival_and_departure_days_allow_empty_without_losing_costs_or_dates():
    req = requirements(arrival_time="19:00", departure_time="10:00")
    data = empty_plan()
    assert report(data, req).passed
    data["costs"]["accommodation"] = 0
    assert "missing_hotel_cost" in codes(report(data, req))
    data["days"].pop()
    assert "date_coverage" in codes(report(data, req))


def test_ordinary_full_day_cannot_be_excused_by_an_empty_generated_day():
    result = report(empty_plan(), requirements())
    assert {"missing_attraction", "missing_daily_meal", "missing_stay_area"} <= codes(result)


def test_short_day_can_still_use_valid_time_but_never_before_arrival():
    req = requirements(arrival_time="19:00", departure_time="10:00")
    data = empty_plan()
    data["days"][0]["stops"] = [{"evidence_id": "a1", "start_time": "20:00", "end_time": "20:30"}]
    assert report(data, req).passed
    data["days"][0]["stops"][0]["start_time"] = "19:30"
    assert "availability_window" in codes(report(data, req))


def test_free_meal_is_also_inside_availability():
    req = requirements(arrival_time="14:00")
    data = candidate()
    data["days"][0]["stops"] = [{"evidence_id": "a1", "start_time": "15:00", "end_time": "16:00"}]
    data["days"][0]["meal_breaks"] = [
        {"anchor_evidence_id": "a1", "start_time": "12:00", "end_time": "13:00"}
    ]
    assert "availability_window" in codes(report(data, req))


def test_user_rest_day_still_cannot_drop_global_must_visit():
    req = requirements(rest_dates=["2026-11-01", "2026-11-02"], must_visit=["西湖"])
    assert "must_visit_missing" in codes(report(empty_plan(), req))


@pytest.mark.parametrize(
    "changes",
    [
        {"rest_dates": ["2026-12-01"]},
        {"rest_dates": ["bad"]},
        {
            "start_date": "2026-11-01",
            "end_date": "2026-11-01",
            "arrival_time": "19:00",
            "departure_time": "10:00",
        },
    ],
)
def test_bad_dates_and_reversed_same_day_times_require_clarification(changes):
    data = requirements().model_dump()
    data.update(changes)
    assert requirement_problems(Requirements.model_validate(data))


def test_mid_trip_rest_retains_date_coverage_and_lodging_budget():
    req = Requirements(
        city="杭州市", start_date="2026-11-01", end_date="2026-11-03", rest_dates=["2026-11-02"]
    )
    data = candidate()
    data["days"][1]["date"] = "2026-11-03"
    data["days"].insert(1, {"date": "2026-11-02", "theme": "休息", "stops": []})
    assert report(data, req).passed


def test_empty_draft_requires_user_availability_and_keeps_must_visit():
    draft = {
        "city": "杭州市",
        "days": [
            {"date": "2026-11-01", "attraction_evidence_ids": []},
            {"date": "2026-11-02", "attraction_evidence_ids": []},
        ],
    }
    facts = [e.model_dump() for e in evidence()]
    assert check_draft(draft, requirements().model_dump(), facts)[0]
    req = requirements(arrival_time="19:00", departure_time="10:00")
    assert not check_draft(draft, req.model_dump(), facts)[0]
    req.must_visit = ["西湖"]
    assert check_draft(draft, req.model_dump(), facts)[0]


def test_no_available_time_is_not_rendered_as_reversed_window():
    req = requirements(arrival_time="23:00", departure_time="06:00")
    assert not day_schedule(req, req.start_date)["has_time"]
    md = render_plan(
        Itinerary.model_validate(empty_plan()), req, evidence(), report(empty_plan(), req)
    )
    assert "接驳后没有可安排的游玩时段" in md
    assert "住宿区域待定" in md and "非导航结果" in md


def test_departure_buffer_crossing_midnight_constrains_previous_evening():
    req = requirements(departure_time="00:30", departure_buffer_minutes=360)
    window = day_schedule(req, req.start_date)
    assert window["end_time"] == "18:30"
    data = candidate()
    data["days"][0]["stops"][1].update(start_time="20:00", end_time="21:00")
    assert "availability_window" in codes(report(data, req))


def test_followup_omission_does_not_erase_other_side_or_rest_dates():
    old = requirements(
        arrival_time="19:00", departure_time="10:00", rest_dates=["2026-11-01"]
    ).model_dump()
    proposed = requirements(departure_time="12:00")
    preserve_schedule(old, proposed, fresh=False)
    assert proposed.arrival_time == "19:00" and proposed.departure_time == "12:00"
    assert proposed.rest_dates == ["2026-11-01"]
    fresh = requirements()
    preserve_schedule(old, fresh, fresh=True)
    assert fresh.arrival_time is None and fresh.rest_dates == []


def test_old_pending_hash_ignores_new_default_fields_but_not_actual_changes():
    import hashlib
    import json

    old = requirements().model_dump()
    for key in (
        "arrival_time",
        "departure_time",
        "arrival_buffer_minutes",
        "departure_buffer_minutes",
        "rest_dates",
    ):
        old.pop(key)
    expected = hashlib.sha256(
        json.dumps(old, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    assert requirements_key(old) == expected
    assert requirements_key({**old, "arrival_time": "19:00"}) != expected


async def test_real_graph_accepts_empty_arrival_return_and_persists_it(monkeypatch, db):
    req = requirements(arrival_time="19:00", departure_time="10:00")
    draft = {
        "city": req.city,
        "days": [
            {"date": d["date"], "theme": d["theme"], "attraction_evidence_ids": []}
            for d in empty_plan()["days"]
        ],
        "rationale": "仅入住和返程",
    }
    _, calls = setup(monkeypatch, req=req, draft=draft, plan=empty_plan())
    result = await TripOrchestrator().plan_trip("empty-arrival", "19点到，次日10点走")
    assert result["status"] == "completed" and result["persisted"]
    assert all(not day["stops"] for day in result["itinerary"]["days"])
    assert not any(name == "attraction" for name, _ in calls)
    assert "住宿区域待定" in result["final_plan_md"]


async def test_understanding_followup_keeps_arrival_when_changing_return_only(monkeypatch):
    req = requirements(departure_time="12:00")
    old = requirements(arrival_time="19:00", departure_time="10:00").model_dump()

    async def ask(*args):
        return RequestDecision(intent="modify_itinerary", requirements=req), {}

    monkeypatch.setattr(pipeline, "ask_json", ask)
    result = await pipeline.understand(
        {
            **initial(),
            "requirements": old,
            "status": "completed",
            "messages": [HumanMessage(content="返程改成中午12点")],
        }
    )
    assert result["requirements"]["arrival_time"] == "19:00"
    assert result["requirements"]["departure_time"] == "12:00"


@pytest.mark.parametrize(
    "target,quote,expected",
    [
        ("arrival_time", "取消抵达时间限制", None),
        ("departure_time", "取消返程时间限制", None),
        ("arrival_time", "不要取消抵达时间限制", "19:00"),
        ("arrival_time", "可以取消抵达时间限制吗？", "19:00"),
        ("arrival_time", "如果取消抵达时间限制会怎样", "19:00"),
        ("arrival_time", "取消返程时间限制，抵达时间保持", "19:00"),
    ],
)
def test_time_release_requires_affirmative_targeted_user_quote(target, quote, expected):
    from app.schemas.planning import ScheduleRelease

    old = requirements(arrival_time="19:00", departure_time="10:00").model_dump()
    req = requirements()
    questions = preserve_schedule(
        old,
        req,
        fresh=False,
        releases=[ScheduleRelease(target=target, user_quote=quote)],
        text=quote,
    )
    assert getattr(req, target) == expected
    assert bool(questions) == (expected is not None)
    assert (
        req.departure_time == "10:00" if target == "arrival_time" else req.arrival_time == "19:00"
    )


def test_cancel_specific_rest_day_keeps_other_rest_days():
    from app.schemas.planning import ScheduleRelease

    old = requirements(rest_dates=["2026-11-01", "2026-11-02"]).model_dump()
    req = requirements()
    quote = "取消2026-11-01休息安排"
    assert not preserve_schedule(
        old,
        req,
        fresh=False,
        releases=[ScheduleRelease(target="rest_date", rest_date="2026-11-01", user_quote=quote)],
        text=quote,
    )
    assert req.rest_dates == ["2026-11-02"]


async def test_failed_availability_edit_cannot_overwrite_formal_plan(monkeypatch, db):
    from sqlalchemy import select

    from app.db.models import Trip

    setup(monkeypatch)
    runner = TripOrchestrator()
    first = await runner.plan_trip("availability-protection", "杭州两天")
    assert first["persisted"]
    async with db() as session:
        before = (await session.execute(select(Trip))).scalar_one().plan_json
    # A model ignores the new arrival requirement; both draft and candidate
    # still use ordinary early-day activities. Acceptance must stop it.
    setup(
        monkeypatch,
        req=requirements(arrival_time="19:00"),
        plan=candidate(),
        intent="modify_itinerary",
    )
    result = await runner.plan_trip("availability-protection", "改为19点才到杭州")
    assert result["status"] == "needs_revision" and not result.get("final_plan_md")
    assert result["accepted_plan"] == first["accepted_plan"]
    assert not result["validation"]["passed"]
    async with db() as session:
        after = (await session.execute(select(Trip))).scalar_one().plan_json
    assert before == after


async def test_legacy_requirements_defaults_do_not_turn_hotel_edit_into_full_replan(monkeypatch):
    req = requirements()
    old = req.model_dump()
    for key in (
        "arrival_time",
        "departure_time",
        "arrival_buffer_minutes",
        "departure_buffer_minutes",
        "rest_dates",
    ):
        old.pop(key)

    async def ask(*args):
        return RequestDecision(intent="modify_hotel", requirements=req), {}

    monkeypatch.setattr(pipeline, "ask_json", ask)
    result = await pipeline.understand(
        {
            **initial(),
            "requirements": old,
            "status": "completed",
            "messages": [HumanMessage(content="仅换酒店，其它不变")],
        }
    )
    assert result["intent"] == "modify_hotel"


@pytest.mark.parametrize(
    "text,target,rest_date,quote",
    [
        ("我没说取消返程时间限制，请保留10点离开的安排", "departure_time", "", "取消返程时间限制"),
        ("取消返程时间限制吗", "departure_time", "", "取消返程时间限制"),
        ("取消2026-11-02休息安排", "rest_date", "", "取消2026-11-02休息安排"),
        (
            "取消2026-11-02休息安排，但2026-11-03休息保留",
            "rest_date",
            "2026-11-03",
            "取消2026-11-02休息安排，但2026-11-03休息保留",
        ),
    ],
)
def test_independent_release_counterexamples_preserve_requirements(text, target, rest_date, quote):
    from app.schemas.planning import ScheduleRelease

    old = requirements(departure_time="10:00", rest_dates=["2026-11-01", "2026-11-02"]).model_dump()
    req = requirements()
    assert preserve_schedule(
        old,
        req,
        fresh=False,
        releases=[ScheduleRelease(target=target, rest_date=rest_date, user_quote=quote)],
        text=text,
    )
    assert req.departure_time == "10:00" and req.rest_dates == old["rest_dates"]


def test_all_rest_dates_release_requires_explicit_all_scope():
    from app.schemas.planning import ScheduleRelease

    old = requirements(rest_dates=["2026-11-01", "2026-11-02"]).model_dump()
    req = requirements()
    text = "取消全部休息日安排"
    assert not preserve_schedule(
        old,
        req,
        fresh=False,
        releases=[ScheduleRelease(target="rest_date", user_quote=text)],
        text=text,
    )
    assert req.rest_dates == []


@pytest.mark.parametrize(
    "text", ["我反对取消返程时间限制", "我讨厌取消返程时间限制", "取消返程时间限制；这只是例子"]
)
def test_cancellation_substring_is_not_an_affirmative_whole_clause(text):
    from app.schemas.planning import ScheduleRelease

    req = requirements()
    old = requirements(departure_time="10:00").model_dump()
    assert preserve_schedule(
        old,
        req,
        fresh=False,
        releases=[ScheduleRelease(target="departure_time", user_quote="取消返程时间限制")],
        text=text,
    )
    assert req.departure_time == "10:00"


@pytest.mark.parametrize(
    "text",
    [
        "我不需要取消返程时间限制",
        "只是讨论取消返程时间限制的影响",
        "假设取消返程时间限制",
        "取消返程时间限制。请保持10点离开不变。",
    ],
)
def test_whole_clause_and_retention_conflict_never_release(text):
    from app.schemas.planning import ScheduleRelease

    req = requirements()
    assert preserve_schedule(
        requirements(departure_time="10:00").model_dump(),
        req,
        fresh=False,
        releases=[ScheduleRelease(target="departure_time", user_quote="取消返程时间限制")],
        text=text,
    )
    assert req.departure_time == "10:00"
