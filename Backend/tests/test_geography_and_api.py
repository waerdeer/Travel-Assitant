"""Regression cases found by actually inspecting generated travel plans."""

import json

import httpx
import pytest
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_closed_loop import candidate, evidence, requirements

from app.graph import pipeline
from app.graph.geography import detail_location
from app.graph.validation import validate_itinerary
from app.mcp.client import MCPClient
from app.schemas.planning import HotelRevision, Itinerary, RequestDecision


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "p1", "location": "120.14,30.24"},
        {"pois": [{"id": "p1", "location": "120.14,30.24"}]},
        [{"id": "p1", "location": "120.14,30.24"}],
    ],
)
def test_detail_parser_accepts_actual_mcp_wrappers(payload):
    content = [{"type": "text", "text": json.dumps(payload)}]
    assert detail_location(content, "p1") == "120.14,30.24"


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "different", "location": "120.14,30.24"},
        {"id": "p1", "location": "nan,nan"},
        {"id": "p1", "location": "500,30"},
        {"id": "p1"},
    ],
)
def test_detail_parser_rejects_wrong_identity_or_coordinates(payload):
    assert detail_location([{"type": "text", "text": json.dumps(payload)}], "p1") is None


def test_cross_district_restaurant_is_rejected_even_in_same_city():
    places = evidence()
    places[2].data["location"] = "119.72,30.23"
    result = validate_itinerary(Itinerary.model_validate(candidate()), requirements(), places)
    assert not result.passed
    assert "long_transfer" in {issue.code for issue in result.issues}


def test_unverified_checks_are_not_reported_as_passed():
    places = evidence()
    for e in places:
        e.data.pop("location")
    result = validate_itinerary(Itinerary.model_validate(candidate()), requirements(), places)
    assert "地理距离" in result.unverified_checks
    assert "地理距离" not in result.checks


def test_explicit_daily_limit_is_stricter_than_pace_default():
    data = candidate()
    data["days"][0]["stops"].append(
        {"evidence_id": "a2", "start_time": "14:00", "end_time": "16:00"}
    )
    result = validate_itinerary(
        Itinerary.model_validate(data), requirements(daily_attraction_limit=1), evidence()
    )
    assert "pace_limit" in {issue.code for issue in result.issues}


async def test_amap_qps_business_error_is_retryable():
    def respond(request):
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "result": {
                    "isError": True,
                    "content": [
                        {"type": "text", "text": "API 调用失败：CUQPS_HAS_EXCEEDED_THE_LIMIT"}
                    ],
                },
            },
        )

    client = MCPClient()
    client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        result = await client._call_tool_http(
            "https://example.test/rpc", "maps_search_detail", {"id": "p1"}
        )
        assert not result.success
        assert result.error_code == "rate_limited"
        assert result.retryable
    finally:
        await client.close()


async def test_hotel_only_edit_cannot_change_days_or_other_costs(monkeypatch):
    previous = candidate()

    async def ask(schema, instruction, context):
        assert schema is HotelRevision
        return HotelRevision(
            hotel_evidence_id="h1", accommodation=150, basis="只调整住宿估算为150元，其他费用沿用"
        ), {"model_calls": 1}

    monkeypatch.setattr(pipeline, "ask_json", ask)
    result = await pipeline.plan(
        {
            "intent": "modify_hotel",
            "requirements": requirements().model_dump(),
            "evidence": [e.model_dump() for e in evidence()],
            "previous_itinerary": previous,
            "messages": [HumanMessage(content="酒店换便宜些，其他别动")],
            "trace": [],
        }
    )
    assert (
        result["itinerary"]["days"]
        == Itinerary.model_validate(previous).model_dump(mode="json")["days"]
    )
    for key in ("meals", "transport", "tickets"):
        assert result["itinerary"]["costs"][key] == previous["costs"][key]
    assert result["itinerary"]["costs"]["accommodation"] == 150


async def test_pacing_edit_reuses_place_evidence(monkeypatch):
    async def ask(schema, instruction, context):
        return RequestDecision(
            intent="modify_itinerary", requirements=requirements(pace="relaxed")
        ), {"model_calls": 1}

    monkeypatch.setattr(pipeline, "ask_json", ask)
    result = await pipeline.understand(
        {
            "requirements": requirements().model_dump(),
            "evidence": [e.model_dump() for e in evidence()],
            "accepted_plan": {"itinerary": candidate()},
            "messages": [HumanMessage(content="轻松一点")],
            "trace": [],
        }
    )
    assert len(result["evidence"]) == 4
    assert result["previous_itinerary"] == candidate()


async def test_recent_message_endpoint_reads_the_actual_latest_rows(monkeypatch, tmp_path):
    from app.db.base import Base
    from app.db.database import get_session
    from app.db.models import Conversation, Message
    from app.main import app

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Conversation(thread_id="long-conversation"))
        await session.flush()
        session.add_all(
            Message(conversation_id="long-conversation", role="user", content=str(i))
            for i in range(110)
        )
        await session.commit()

    async def session_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/conversations/long-conversation?message_limit=10")
        assert response.status_code == 200
        assert [m["content"] for m in response.json()["recent_messages"]] == [
            str(i) for i in range(100, 110)
        ]
    finally:
        app.dependency_overrides.pop(get_session)
        await engine.dispose()


async def test_sse_sends_actual_progress_then_one_terminal_result(monkeypatch):
    from app.agents.orchestrator import TripOrchestrator
    from app.main import app

    async def run(self, thread_id, text, on_event=None, **kwargs):
        if on_event:
            await on_event(
                {"node": "understand", "trace": [{"stage": "understand", "summary": "需补充日期"}]}
            )
        return {
            "intent": "new_trip",
            "status": "awaiting_clarification",
            "reply": "请提供出发日期",
            "persisted": True,
        }

    monkeypatch.setattr(TripOrchestrator, "plan_trip", run)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/chat_plan/stream", json={"thread_id": "sse-test", "text": "去杭州"}
        )
        blank = await client.post("/api/v1/chat_plan", json={"text": "   "})
    assert response.status_code == 200
    assert response.text.index("event: progress") < response.text.index("event: result")
    assert response.text.count("event: result") == 1
    assert "请提供出发日期" in response.text
    assert blank.status_code == 422


async def test_spatial_failure_changes_retrieval_strategy_before_replanning(monkeypatch):
    from app.graph import research, workflow
    from app.schemas.planning import Evidence

    places = evidence()
    places[2].data["location"] = "119.72,30.23"
    calls = []
    plans = []

    async def ask(schema, instruction, context):
        if schema is RequestDecision:
            return RequestDecision(intent="modify_itinerary", requirements=requirements()), {
                "model_calls": 1
            }
        data = candidate()
        if any(e["evidence_id"] == "r2" for e in context["evidence"]):
            for day in data["days"]:
                for stop in day["stops"]:
                    if stop["evidence_id"] == "r1":
                        stop["evidence_id"] = "r2"
        plans.append(data)
        return Itinerary.model_validate(data), {"model_calls": 1}

    async def search(category, args, remaining):
        calls.append(category)
        found = []
        if category == "nearby":
            found = [
                Evidence(
                    evidence_id="r2",
                    category="restaurant",
                    city="杭州市",
                    fetched_at=places[0].fetched_at,
                    data={
                        "id": "r2",
                        "name": "真正附近的餐厅",
                        "location": "120.14,30.24",
                        "address": "景点附近",
                    },
                ).model_dump()
            ]
        return found, [{"stage": "tool", "tool": "test_search", "ok": True, "count": len(found)}], 1

    monkeypatch.setattr(pipeline, "ask_json", ask)
    monkeypatch.setattr(research, "execute_search", search)
    graph = workflow.build_workflow().compile()
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="检查路线")],
            "requirements": requirements().model_dump(),
            "evidence": [e.model_dump() for e in places],
            "trace": [],
            "metrics": {},
            "repair_count": 0,
        }
    )
    assert result["status"] == "completed"
    assert result["research_round"] == 2
    assert "nearby" in calls
    assert len(plans) == 2
    assert [e["passed"] for e in result["trace"] if e["stage"] == "validate"] == [False, True]
    assert "真正附近的餐厅" in result["final_plan_md"]
