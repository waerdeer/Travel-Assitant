"""Semantic decisions and deterministic acceptance gates are separate nodes."""

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.graph.choices import after_review, apply_selection, review_options
from app.graph.drafts import build_route_draft, enrich_route_draft
from app.graph.geography import enrich_locations
from app.graph.pipeline import (
    after_plan,
    after_understand,
    after_validate,
    deliver,
    plan,
    understand,
    validate,
)
from app.graph.research import collect_evidence, collect_route_evidence
from app.graph.state import TripState


def build_workflow() -> StateGraph:
    graph = StateGraph(TripState)

    def register(name, function):
        async def execute(state):
            get_stream_writer()({"node": name, "phase": "start", "trace": state.get("trace", [])})
            return await function(state)

        graph.add_node(name, execute)

    for name, function in (
        ("understand", understand),
        ("research", collect_evidence),
        ("plan", plan),
        ("validate", validate),
        ("geography", enrich_locations),
        ("deliver", deliver),
        ("review_options", review_options),
        ("apply_selection", apply_selection),
        ("route_research", collect_route_evidence),
        ("draft_route", build_route_draft),
        ("draft_geography", enrich_route_draft),
    ):
        register(name, function)
    graph.add_conditional_edges(
        START,
        lambda state: "apply_selection" if state.get("choice_selection") else "understand",
        {"apply_selection": "apply_selection", "understand": "understand"},
    )
    graph.add_conditional_edges(
        "apply_selection",
        lambda state: "plan" if state.get("status") == "planning" else "deliver",
        {"plan": "plan", "deliver": "deliver"},
    )
    graph.add_conditional_edges(
        "understand",
        lambda state: (
            "deliver"
            if after_understand(state) == "deliver"
            else (
                "route_research" if state.get("planning_strategy") == "route_first" else "research"
            )
        ),
        {"deliver": "deliver", "research": "research", "route_research": "route_research"},
    )
    graph.add_edge("route_research", "draft_route")
    graph.add_conditional_edges(
        "draft_route",
        lambda state: "draft_geography" if state.get("route_draft") else "deliver",
        {"draft_geography": "draft_geography", "deliver": "deliver"},
    )
    graph.add_conditional_edges(
        "draft_geography",
        lambda state: "research" if state.get("route_draft") else "deliver",
        {"research": "research", "deliver": "deliver"},
    )
    graph.add_edge("research", "review_options")
    graph.add_conditional_edges(
        "review_options", after_review, {"deliver": "deliver", "plan": "plan"}
    )
    graph.add_conditional_edges("plan", after_plan, {"validate": "geography", "deliver": "deliver"})
    graph.add_edge("geography", "validate")
    graph.add_conditional_edges(
        "validate", after_validate, {"research": "research", "plan": "plan", "deliver": "deliver"}
    )
    graph.add_edge("deliver", END)
    return graph


# persistence.py commits durable turn snapshots together with messages. This
# supports turn-level recovery, not resuming midway through an interrupted node.
app_graph = build_workflow().compile()
