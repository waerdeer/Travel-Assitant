"""Expected behavior for the independent review's F1–F4 counterexamples.

Real production graph, deterministic external responses; no user DB or network.
"""

from copy import deepcopy
import pytest
from langchain_core.messages import HumanMessage
from test_closed_loop import candidate, install_graph
from test_human_choices import pending_state, selected

from app.graph import choices, pipeline, research, workflow
from app.graph.place_policy import unavailable_place
from app.schemas.planning import ChoiceSelection, Itinerary


@pytest.mark.parametrize(
    "name",
    [
        "湖畔酒店(停业)",
        "湖畔酒店（停业）",
        "酒店 暂停营业",
        "酒店(建设中)",
        "酒店【未开业】",
        "酒店(关闭)",
    ],
)
def test_explicit_unavailable_name_is_excluded(name):
    assert unavailable_place({"name": name})


@pytest.mark.parametrize("name", ["不停业酒馆", "关闭烦恼咖啡馆", "停业路酒店", "建设路酒店"])
def test_ordinary_name_is_not_an_operating_status(name):
    assert not unavailable_place({"name": name})


@pytest.mark.parametrize("field", ["status", "business_status", "operating_status"])
def test_explicit_operating_status_is_excluded(field):
    assert unavailable_place({"name": "湖畔酒店", field: "closed"})
    assert not unavailable_place({"name": "湖畔酒店", field: "unknown"})


async def test_bare_closed_marker_rejected_on_legacy_manual_resume(monkeypatch):
    base = await pending_state()
    base["pending_choice"]["hotels"][0]["name"] = "湖畔酒店(停业)"
    for item in base["evidence"]:
        if item["evidence_id"] == "h1":
            item["data"]["name"] = "湖畔酒店(停业)"
    graph, calls = install_graph(monkeypatch)
    with pytest.raises(choices.ChoiceConflict, match="停业"):
        await graph.ainvoke(
            {**base, "choice_selection": selected(base["pending_choice"]).model_dump()}
        )
    assert not calls
    assert not choices.shortlist(base["evidence"], "hotel", 4)


async def construction_pending():
    base = await pending_state()
    for option in base["pending_choice"]["hotels"]:
        option["name"] = "湖畔酒店(建设中)"
    for item in base["evidence"]:
        if item["category"] == "hotel":
            item["data"]["name"] = "湖畔酒店(建设中)"
    return base


async def test_automatic_all_invalid_hotel_candidates_rejected_before_model(monkeypatch):
    base = await construction_pending()
    graph, calls = install_graph(
        monkeypatch, candidates=[{**candidate(), "hotel_evidence_id": None}]
    )
    decision = ChoiceSelection(token=base["pending_choice"]["token"], automatic=True)
    with pytest.raises(choices.ChoiceConflict, match="全部过期或不可用"):
        await graph.ainvoke({**base, "choice_selection": decision.model_dump()})
    assert not calls


async def test_automatic_can_use_remaining_valid_hotel(monkeypatch):
    base = await construction_pending()
    valid = deepcopy(next(item for item in base["evidence"] if item["category"] == "hotel"))
    valid["evidence_id"] = "h2"
    valid["data"].update(id="h2", name="可用酒店")
    base["evidence"].append(valid)
    base["pending_choice"]["hotels"] += choices.shortlist([valid], "hotel", 1)
    plan = {**candidate(), "hotel_evidence_id": "h2"}
    graph, calls = install_graph(monkeypatch, candidates=[plan])
    result = await graph.ainvoke(
        {
            **base,
            "messages": [HumanMessage(content="自动安排")],
            "metrics": {},
            "repair_count": 0,
            "choice_selection": ChoiceSelection(
                token=base["pending_choice"]["token"], automatic=True
            ).model_dump(),
        }
    )
    assert result["status"] == "completed"
    assert result["itinerary"]["hotel_evidence_id"] == "h2"
    assert "建设中" not in result["final_plan_md"]
    assert [name for name, _ in calls] == ["Itinerary"]


async def test_unavailable_selected_hotel_cannot_be_reduced_to_warning(monkeypatch):
    base = await construction_pending()
    accepted = {"itinerary": candidate(), "plan_md": "原有效版本"}
    base.update(
        choice_confirmed=True, selected_options={"hotel_evidence_id": "h1"}, accepted_plan=accepted
    )
    review = await choices.review_options(base)
    assert review["status"] == "blocked"
    no_hotel = {**candidate(), "hotel_evidence_id": None}
    result = await pipeline.validate({**base, "itinerary": no_hotel, "repair_count": 1})
    assert not result["validation"]["passed"]
    assert {"selected_hotel_unavailable", "selected_hotel_changed"} <= {
        issue["code"] for issue in result["validation"]["issues"] if issue["severity"] == "error"
    }

    async def forbidden(*args, **kwargs):
        pytest.fail("unavailable chosen constraint must stop before a model call")

    monkeypatch.setattr(pipeline, "ask_json", forbidden)
    stopped = await pipeline.plan(base)
    delivered = await pipeline.deliver({**base, **stopped})
    assert delivered["status"] == "blocked" and not delivered["final_plan_md"]
    assert "accepted_plan" not in delivered
    assert base["accepted_plan"] == accepted


async def test_missing_data_warning_remains_possible_without_a_chosen_hotel():
    base = await pending_state()
    base["evidence"] = [e for e in base["evidence"] if e["category"] != "hotel"]
    result = await pipeline.validate(
        {**base, "itinerary": {**candidate(), "hotel_evidence_id": None}, "repair_count": 1}
    )
    assert result["validation"]["passed"]
    assert any(
        i["code"] == "missing_hotel" and i["severity"] == "warning"
        for i in result["validation"]["issues"]
    )


async def test_legacy_regional_pending_requires_scope_confirmation_without_planning(monkeypatch):
    base = await pending_state()
    base["pending_choice"].pop("scope_policy_version", None)
    base["requirements"].update(city="阿勒泰", end_date="2026-11-07", duration_days=7)
    base["pending_choice"].update(city="阿勒泰", intent="new_trip")
    base["messages"] = [HumanMessage(content="去北疆高级奢华游 下周一整周")]
    for item in base["evidence"]:
        item["city"] = "阿勒泰"
    graph, calls = install_graph(monkeypatch)
    result = await graph.ainvoke(
        {**base, "metrics": {}, "choice_selection": selected(base["pending_choice"]).model_dump()}
    )
    assert result["status"] == "awaiting_clarification"
    assert "旧版规划规则" in result["reply"]
    assert not result["pending_choice"] and not result["final_plan_md"]
    assert not calls
    assert result["requirements"]["duration_days"] == 7


async def test_current_policy_resume_does_not_repeat_understanding(monkeypatch):
    base = await pending_state()
    graph, calls = install_graph(monkeypatch)
    result = await graph.ainvoke(
        {
            **base,
            "messages": [HumanMessage(content="继续")],
            "metrics": {},
            "repair_count": 0,
            "choice_selection": selected(base["pending_choice"]).model_dump(),
        }
    )
    assert result["status"] == "completed"
    assert [name for name, _ in calls] == ["Itinerary"]


async def test_empty_nearby_identical_retry_stops_before_any_more_calls(monkeypatch):
    base = await pending_state()
    base["intent"] = base["pending_choice"]["intent"] = "new_trip"
    base["decision"] = {"food_query": "当地菜"}
    for item in base["evidence"]:
        if item["category"] == "restaurant":
            item["data"]["location"] = "120.90,30.24"
    tool_calls, model_calls = [], []

    async def empty(category, args, remaining):
        tool_calls.append(category)
        return [], [{"stage": "tool", "tool": "nearby", "ok": True, "count": 0}], 1

    async def ask(schema, instruction, context):
        model_calls.append(schema.__name__)
        return Itinerary.model_validate(candidate()), {"model_calls": 1}

    monkeypatch.setattr(research, "execute_search", empty)
    monkeypatch.setattr(pipeline, "ask_json", ask)
    graph = workflow.build_workflow().compile()
    result = await graph.ainvoke(
        {
            **base,
            "messages": [HumanMessage(content="继续")],
            "metrics": {},
            "repair_count": 0,
            "research_round": 0,
            "tool_calls": 0,
            "choice_selection": selected(base["pending_choice"]).model_dump(),
        }
    )
    assert result["status"] == "awaiting_choice"
    assert result["pending_choice"]["no_progress"]
    assert "没有找到新的可用候选" in result["reply"]
    assert {"h1", "r1"} <= {e["evidence_id"] for e in result["evidence"]}
    pending = result["pending_choice"]
    retry = ChoiceSelection(token=pending["token"], restaurant_evidence_ids=["r1"])
    before = len(tool_calls)
    for _ in range(3):
        with pytest.raises(choices.ChoiceConflict, match="相同条件与选择"):
            await graph.ainvoke(
                {
                    **result,
                    "choice_selection": retry.model_dump(),
                    "trace": [],
                    "metrics": {},
                    "repair_count": 0,
                    "research_round": 0,
                    "tool_calls": 0,
                }
            )
    assert model_calls == ["Itinerary"]
    assert len(tool_calls) == before
    assert result["pending_choice"]["token"] == pending["token"]
    # Releasing the affected hard restaurant pool is a material change, so auto is allowed.
    assert not pending["automatic_retry_blocked"]
    choices.validate_selection(result, ChoiceSelection(token=pending["token"], automatic=True))


@pytest.mark.parametrize("field", ["status", "business_status", "operating_status"])
@pytest.mark.parametrize("value", ["暂停营业", "暂不营业", "已关闭", "已停业"])
def test_chinese_status_fields_match_name_policy(field, value):
    from app.graph.tools import _normalize_poi

    raw = {"id": "h1", "name": "湖畔酒店", "typecode": "100100", field: value}
    assert unavailable_place(raw)
    assert _normalize_poi(raw) is None
    assert not unavailable_place({"name": "湖畔酒店", field: "正常营业"})


async def test_chinese_status_in_selected_evidence_prevents_formal_plan(monkeypatch):
    base = await pending_state()
    next(e for e in base["evidence"] if e["evidence_id"] == "h1")["data"]["business_status"] = (
        "暂停营业"
    )
    graph, calls = install_graph(monkeypatch)
    with pytest.raises(choices.ChoiceConflict):
        await graph.ainvoke(
            {**base, "choice_selection": selected(base["pending_choice"]).model_dump()}
        )
    assert not calls


@pytest.mark.parametrize(
    "category,ref", [("hotel", "h1"), ("restaurant", "r1"), ("attraction", "a1")]
)
@pytest.mark.parametrize("coordinates", [True, False])
async def test_detail_negative_signal_stops_formal_delivery_and_preserves_accepted_plan(
    monkeypatch, category, ref, coordinates
):
    from types import SimpleNamespace
    from app.graph import geography

    base = await pending_state()
    base["intent"] = base["pending_choice"]["intent"] = "modify_itinerary"
    accepted = {"itinerary": candidate(), "plan_md": "已保存的原正式版"}
    base["accepted_plan"] = deepcopy(accepted)
    target = next(e for e in base["evidence"] if e["evidence_id"] == ref)
    target["data"].pop("location", None)

    async def detail(server, tool, args):
        assert args["id"] == ref
        poi = {"id": ref, "name": "来源地点(停业)", "business_status": "closed"}
        if coordinates:
            poi["location"] = "120.14,30.24"
        return SimpleNamespace(
            success=True, error_code=None, retryable=False, content=[{"pois": [poi]}]
        )

    monkeypatch.setattr(geography.mcp_client, "call_tool", detail)
    graph, calls = install_graph(monkeypatch)
    result = await graph.ainvoke(
        {
            **base,
            "messages": [HumanMessage(content="继续")],
            "metrics": {},
            "repair_count": 0,
            "choice_selection": selected(base["pending_choice"]).model_dump(),
        }
    )
    assert result["status"] not in ("completed", "degraded")
    assert not result["final_plan_md"]
    updated = next(e for e in result["evidence"] if e["evidence_id"] == ref)
    assert updated["data"]["business_status"] == "closed"
    assert updated["data"]["availability_source"] == "maps_search_detail"
    assert updated["data"]["availability_detail_name"] == "来源地点(停业)"
    assert result["accepted_plan"] == accepted
    assert any(e.get("unavailable") and e["ok"] for e in result["trace"] if e["stage"] == "tool")


@pytest.mark.parametrize("detail_id", ["different", None])
async def test_unmatched_detail_cannot_poison_original_availability(monkeypatch, detail_id):
    from types import SimpleNamespace
    from app.graph import geography

    base = await pending_state()
    next(e for e in base["evidence"] if e["evidence_id"] == "h1")["data"].pop("location", None)

    async def detail(server, tool, args):
        poi = {"name": "其他酒店(停业)", "location": "120.14,30.24", "status": "closed"}
        if detail_id:
            poi["id"] = detail_id
        return SimpleNamespace(
            success=True, error_code=None, retryable=False, content=[{"pois": [poi]}]
        )

    monkeypatch.setattr(geography.mcp_client, "call_tool", detail)
    graph, _ = install_graph(monkeypatch)
    result = await graph.ainvoke(
        {
            **base,
            "messages": [HumanMessage(content="继续")],
            "metrics": {},
            "repair_count": 0,
            "choice_selection": selected(base["pending_choice"]).model_dump(),
        }
    )
    target = next(e for e in result["evidence"] if e["evidence_id"] == "h1")
    assert not unavailable_place(target["data"])
    assert "availability_source" not in target["data"]
    assert "location" not in target["data"]
    assert "地理距离" in result["validation"]["unverified_checks"]


async def test_matching_normal_detail_keeps_coordinate_enrichment(monkeypatch):
    from types import SimpleNamespace
    from app.graph import geography

    base = await pending_state()
    next(e for e in base["evidence"] if e["evidence_id"] == "h1")["data"].pop("location", None)

    async def detail(server, tool, args):
        return SimpleNamespace(
            success=True,
            error_code=None,
            retryable=False,
            content=[
                {
                    "pois": [
                        {
                            "id": "h1",
                            "name": "正常酒店",
                            "location": "120.14,30.24",
                            "business_status": "正常营业",
                        }
                    ]
                }
            ],
        )

    monkeypatch.setattr(geography.mcp_client, "call_tool", detail)
    graph, _ = install_graph(monkeypatch)
    result = await graph.ainvoke(
        {
            **base,
            "messages": [HumanMessage(content="继续")],
            "metrics": {},
            "repair_count": 0,
            "choice_selection": selected(base["pending_choice"]).model_dump(),
        }
    )
    assert result["status"] == "completed"
    target = next(e for e in result["evidence"] if e["evidence_id"] == "h1")
    assert target["data"]["location"] == "120.14,30.24"
    assert not unavailable_place(target["data"])


async def test_automatic_detail_closed_hotel_cannot_be_silently_omitted(monkeypatch):
    from types import SimpleNamespace
    from app.graph import geography

    base = await pending_state()
    base["intent"] = base["pending_choice"]["intent"] = "new_trip"
    next(e for e in base["evidence"] if e["evidence_id"] == "h1")["data"].pop("location", None)

    async def detail(server, tool, args):
        return SimpleNamespace(
            success=True,
            error_code=None,
            retryable=False,
            content=[{"pois": [{"id": "h1", "business_status": "closed"}]}],
        )

    monkeypatch.setattr(geography.mcp_client, "call_tool", detail)
    graph, calls = install_graph(
        monkeypatch, candidates=[candidate(), {**candidate(), "hotel_evidence_id": None}]
    )
    result = await graph.ainvoke(
        {
            **base,
            "messages": [HumanMessage(content="自动安排")],
            "metrics": {},
            "repair_count": 0,
            "choice_selection": ChoiceSelection(
                token=base["pending_choice"]["token"], automatic=True
            ).model_dump(),
        }
    )
    assert result["status"] == "blocked" and not result["final_plan_md"]
    assert [name for name, _ in calls] == ["Itinerary"]


async def test_automatic_can_replace_detail_closed_hotel_with_valid_alternative(monkeypatch):
    from types import SimpleNamespace
    from app.graph import geography

    base = await pending_state()
    base["intent"] = base["pending_choice"]["intent"] = "new_trip"
    old = next(e for e in base["evidence"] if e["evidence_id"] == "h1")
    alternative = deepcopy(old)
    alternative["evidence_id"] = "h2"
    alternative["data"].update(id="h2", name="有效替代酒店")
    base["evidence"].append(alternative)
    base["pending_choice"]["hotels"] += choices.shortlist([alternative], "hotel", 1)
    old["data"].pop("location", None)

    async def detail(server, tool, args):
        return SimpleNamespace(
            success=True,
            error_code=None,
            retryable=False,
            content=[
                {"pois": [{"id": "h1", "business_status": "closed", "location": "120.14,30.24"}]}
            ],
        )

    monkeypatch.setattr(geography.mcp_client, "call_tool", detail)
    graph, _ = install_graph(
        monkeypatch, candidates=[candidate(), {**candidate(), "hotel_evidence_id": "h2"}]
    )
    result = await graph.ainvoke(
        {
            **base,
            "messages": [HumanMessage(content="自动安排")],
            "metrics": {},
            "repair_count": 0,
            "choice_selection": ChoiceSelection(
                token=base["pending_choice"]["token"], automatic=True
            ).model_dump(),
        }
    )
    assert result["status"] == "completed"
    assert result["itinerary"]["hotel_evidence_id"] == "h2"
    assert "有效替代酒店" in result["final_plan_md"]


async def test_closed_fact_survives_unrelated_spatial_research_and_durable_resume(monkeypatch):
    from types import SimpleNamespace
    from app.graph import geography

    base = await pending_state()
    base["intent"] = base["pending_choice"]["intent"] = "modify_itinerary"
    accepted = {"itinerary": candidate(), "plan_md": "原正式版"}
    base.update(accepted_plan=deepcopy(accepted), decision={"food_query": "本地菜"})
    next(e for e in base["evidence"] if e["evidence_id"] == "h1")["data"].pop("location", None)
    restaurant = next(e for e in base["evidence"] if e["evidence_id"] == "r1")
    restaurant["data"]["location"] = "120.90,30.24"
    nearby = deepcopy(restaurant)
    nearby["evidence_id"] = "r2"
    nearby["data"].update(id="r2", name="附近餐厅", location="120.14,30.24")

    async def detail(server, tool, args):
        return SimpleNamespace(
            success=True,
            error_code=None,
            retryable=False,
            content=[
                {"pois": [{"id": "h1", "business_status": "closed", "location": "120.14,30.24"}]}
            ],
        )

    async def search(category, args, remaining):
        assert category == "nearby"
        return [nearby], [{"stage": "tool", "tool": "nearby", "ok": True, "count": 1}], 1

    calls = []

    async def ask(schema, instruction, context):
        calls.append(schema.__name__)
        plan = candidate()
        if len(calls) > 1:
            plan["hotel_evidence_id"] = None
            for day in plan["days"]:
                for stop in day["stops"]:
                    if stop["evidence_id"] == "r1":
                        stop["evidence_id"] = "r2"
        return Itinerary.model_validate(plan), {"model_calls": 1}

    monkeypatch.setattr(geography.mcp_client, "call_tool", detail)
    monkeypatch.setattr(research, "execute_search", search)
    monkeypatch.setattr(pipeline, "ask_json", ask)
    graph = workflow.build_workflow().compile()
    result = await graph.ainvoke(
        {
            **base,
            "messages": [HumanMessage(content="自动安排")],
            "metrics": {},
            "repair_count": 0,
            "research_round": 0,
            "tool_calls": 0,
            "choice_selection": ChoiceSelection(
                token=base["pending_choice"]["token"], automatic=True
            ).model_dump(),
        }
    )
    assert result["status"] == "awaiting_choice"
    assert (
        next(e for e in result["evidence"] if e["evidence_id"] == "h1")["data"]["business_status"]
        == "closed"
    )
    # The same primitive facts survive JSON snapshot serialization.
    import json

    result["evidence"] = json.loads(json.dumps(result["evidence"]))
    result = await graph.ainvoke(
        {
            **result,
            "metrics": {},
            "repair_count": 0,
            "research_round": 0,
            "tool_calls": 0,
            "choice_selection": ChoiceSelection(
                token=result["pending_choice"]["token"], restaurant_evidence_ids=["r2"]
            ).model_dump(),
        }
    )
    assert result["status"] == "blocked" and not result["final_plan_md"]
    assert result["accepted_plan"] == accepted
    assert calls == ["Itinerary"]


@pytest.mark.parametrize("category", ["hotel", "restaurant", "attraction"])
async def test_research_keeps_negative_facts_out_of_candidates_but_in_store(monkeypatch, category):
    base = await pending_state()
    target = next(e for e in base["evidence"] if e["category"] == category)
    target["data"]["business_status"] = "closed"
    base["decision"] = {}

    async def empty(kind, args, remaining):
        return [], [], 1

    monkeypatch.setattr(research, "execute_search", empty)
    result = await research.collect_evidence(base)
    assert (
        next(e for e in result["evidence"] if e["evidence_id"] == target["evidence_id"])["data"][
            "business_status"
        ]
        == "closed"
    )
    assert target["evidence_id"] not in {
        e["evidence_id"] for e in choices.available_evidence({**base, **result})
    }


async def test_explicit_refresh_keeps_known_closure_until_source_updates(monkeypatch):
    from app.schemas.planning import RequestDecision
    from test_closed_loop import requirements

    base = await construction_pending()

    async def ask(schema, instruction, context):
        return RequestDecision(
            intent="modify_hotel", requirements=requirements(), refresh_categories=["hotel"]
        ), {"model_calls": 1}

    monkeypatch.setattr(pipeline, "ask_json", ask)
    result = await pipeline.understand(
        {**base, "messages": [HumanMessage(content="换一批酒店")], "metrics": {}}
    )
    assert any(unavailable_place(e["data"]) for e in result["evidence"])


@pytest.mark.parametrize(
    "positive,newer,allowed",
    [(None, True, False), ("正常营业", False, False), ("正常营业", True, True)],
)
async def test_known_closure_requires_newer_explicit_source_status(positive, newer, allowed):
    from datetime import datetime, timedelta, timezone

    base = await pending_state()
    old = deepcopy(next(e for e in base["evidence"] if e["category"] == "hotel"))
    instant = datetime.now(timezone.utc)
    old["fetched_at"] = instant.isoformat()
    old["data"]["business_status"] = "closed"
    update = deepcopy(old)
    update["data"].pop("business_status")
    update["fetched_at"] = (instant + timedelta(seconds=1 if newer else -1)).isoformat()
    if positive:
        update["data"]["business_status"] = positive
    result = research.merge_evidence([old, update])[0]
    assert (not unavailable_place(result["data"])) == allowed
    if not allowed:
        assert result["fetched_at"] == old["fetched_at"]


def test_street_named_jianshezhonglu_is_not_a_construction_status():
    assert not unavailable_place({"name": "如家酒店(建设中路店)"})
    assert unavailable_place({"name": "如家酒店(建设中)"})


async def test_recent_closure_has_its_own_ttl_even_when_original_search_is_old():
    from datetime import datetime, timedelta, timezone

    base = await pending_state()
    hotel = deepcopy(next(e for e in base["evidence"] if e["evidence_id"] == "h1"))
    now = datetime.now(timezone.utc)
    hotel["fetched_at"] = (now - timedelta(hours=6, minutes=1)).isoformat()
    hotel["data"].update(
        business_status="closed",
        availability_source="maps_search_detail",
        availability_fetched_at=(now - timedelta(minutes=2)).isoformat(),
    )
    stored = research.fresh_evidence([hotel], hotel["city"], include_unavailable=True)
    assert stored and stored[0]["data"]["business_status"] == "closed"
    assert not research.fresh_evidence([hotel], hotel["city"])
    # Real closure age eventually expires; merely re-reading it does not renew it.
    hotel["data"]["availability_fetched_at"] = (now - timedelta(hours=6, minutes=1)).isoformat()
    assert not research.fresh_evidence([hotel], hotel["city"], include_unavailable=True)


async def test_merge_order_cannot_overwrite_new_operating_status_with_old_closure():
    from datetime import datetime, timedelta, timezone

    base = await pending_state()
    old = deepcopy(next(e for e in base["evidence"] if e["evidence_id"] == "h1"))
    now = datetime.now(timezone.utc)
    old["fetched_at"] = (now - timedelta(minutes=10)).isoformat()
    old["data"]["business_status"] = "closed"
    opened = deepcopy(old)
    opened["fetched_at"] = now.isoformat()
    opened["data"]["business_status"] = "正常营业"
    for ordered in ([old, opened], [opened, old], [old, opened, old]):
        result = research.merge_evidence(ordered)[0]
        assert result["data"]["business_status"] == "正常营业"
        assert result["fetched_at"] == now.isoformat()


async def test_detail_signal_time_wins_over_newer_retrieval_without_status():
    from datetime import datetime, timedelta, timezone

    base = await pending_state()
    closed = deepcopy(next(e for e in base["evidence"] if e["evidence_id"] == "h1"))
    now = datetime.now(timezone.utc)
    closed["fetched_at"] = (now - timedelta(hours=5)).isoformat()
    closed["data"].update(business_status="closed", availability_fetched_at=now.isoformat())
    stale_open = deepcopy(closed)
    stale_open["fetched_at"] = (now - timedelta(minutes=1)).isoformat()
    stale_open["data"]["business_status"] = "正常营业"
    merged = research.merge_evidence([closed, stale_open])[0]
    assert unavailable_place(merged["data"])
    assert research.fact_time(merged) == now


@pytest.mark.parametrize("with_alternative", [False, True])
async def test_new_detail_closure_near_old_ttl_survives_spatial_repair(
    monkeypatch, with_alternative
):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from app.graph import geography

    base = await pending_state()
    base["intent"] = base["pending_choice"]["intent"] = "modify_itinerary"
    accepted = {"itinerary": candidate(), "plan_md": "原正式版"}
    base.update(accepted_plan=deepcopy(accepted), decision={"food_query": "本地菜"})
    clock = [datetime.now(timezone.utc)]
    hotel = next(e for e in base["evidence"] if e["evidence_id"] == "h1")
    hotel["data"].pop("location", None)
    hotel["fetched_at"] = (clock[0] - timedelta(hours=5, minutes=59)).isoformat()
    if with_alternative:
        alt = deepcopy(hotel)
        alt["evidence_id"] = "h2"
        alt["data"].update(id="h2", name="可用替代酒店", location="120.14,30.24")
        alt["fetched_at"] = clock[0].isoformat()
        base["evidence"].append(alt)
        base["pending_choice"]["hotels"] += choices.shortlist([alt], "hotel", 1)
    restaurant = next(e for e in base["evidence"] if e["evidence_id"] == "r1")
    restaurant["data"]["location"] = "120.90,30.24"
    nearby = deepcopy(restaurant)
    nearby["evidence_id"] = "r2"
    nearby["data"].update(id="r2", name="附近餐厅", location="120.14,30.24")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0] if tz else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(research, "datetime", Clock)
    monkeypatch.setattr(geography, "datetime", Clock)

    async def detail(server, tool, args):
        clock[0] += timedelta(minutes=2)
        return SimpleNamespace(
            success=True,
            error_code=None,
            retryable=False,
            content=[{"pois": [{"id": "h1", "status": "closed", "location": "120.14,30.24"}]}],
        )

    async def search(category, args, remaining):
        assert category == "nearby"
        return [nearby], [{"stage": "tool", "tool": "nearby", "ok": True, "count": 1}], 1

    calls = []

    async def ask(schema, instruction, context):
        calls.append(schema.__name__)
        plan = candidate()
        if len(calls) > 1:
            plan["hotel_evidence_id"] = "h2" if with_alternative else None
            for day in plan["days"]:
                for stop in day["stops"]:
                    if stop["evidence_id"] == "r1":
                        stop["evidence_id"] = "r2"
        return Itinerary.model_validate(plan), {"model_calls": 1}

    monkeypatch.setattr(geography.mcp_client, "call_tool", detail)
    monkeypatch.setattr(research, "execute_search", search)
    monkeypatch.setattr(pipeline, "ask_json", ask)
    graph = workflow.build_workflow().compile()
    out = await graph.ainvoke(
        {
            **base,
            "messages": [HumanMessage(content="自动安排")],
            "metrics": {},
            "repair_count": 0,
            "research_round": 0,
            "tool_calls": 0,
            "choice_selection": ChoiceSelection(
                token=base["pending_choice"]["token"], automatic=True
            ).model_dump(),
        }
    )
    assert out["status"] == "awaiting_choice"
    assert any(
        e["evidence_id"] == "h1" and e["data"].get("business_status") == "closed"
        for e in out["evidence"]
    )
    out = await graph.ainvoke(
        {
            **out,
            "metrics": {},
            "repair_count": 0,
            "research_round": 0,
            "tool_calls": 0,
            "choice_selection": ChoiceSelection(
                token=out["pending_choice"]["token"], restaurant_evidence_ids=["r2"]
            ).model_dump(),
        }
    )
    if with_alternative:
        assert out["status"] == "completed" and out["itinerary"]["hotel_evidence_id"] == "h2"
    else:
        assert out["status"] == "blocked" and not out["final_plan_md"]
        assert out["accepted_plan"] == accepted


async def test_equal_time_conflicting_status_is_conservatively_closed():
    base = await pending_state()
    opened = deepcopy(next(e for e in base["evidence"] if e["evidence_id"] == "h1"))
    opened["data"]["business_status"] = "正常营业"
    closed = deepcopy(opened)
    closed["data"]["business_status"] = "closed"
    for ordered in ([opened, closed], [closed, opened]):
        assert unavailable_place(research.merge_evidence(ordered)[0]["data"])
