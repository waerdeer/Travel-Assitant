"""A durable business-level human decision boundary, without a live coroutine.

The pending token and candidate IDs are committed in the same turn snapshot as
the conversation. Resume validates the token under the conversation lock;
arbitrary or stale IDs can never become planner constraints.
"""

import hashlib
import json
import re
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from app.graph.anchors import anchor_issues, name_matches
from app.graph.place_policy import unavailable_place
from app.graph.research import fresh_evidence
from app.schemas.planning import ChoiceSelection, ValidationIssue

SCOPE_POLICY_VERSION = 1


class ChoiceConflict(ValueError):
    pass


def available_evidence(state: dict) -> list[dict]:
    return fresh_evidence(state.get("evidence", []), state.get("requirements", {}).get("city", ""))


def resumed_constraints(state: dict, pending: dict, selection: ChoiceSelection) -> dict:
    chosen = dict(state.get("selected_options", {}))
    for category, key, value in (
        ("hotels", "hotel_evidence_id", selection.hotel_evidence_id),
        ("restaurants", "restaurant_evidence_ids", selection.restaurant_evidence_ids),
    ):
        if pending[category]:
            chosen.pop(key, None)
            mode = selection.hotel_mode if category == "hotels" else selection.restaurant_mode
            if not selection.automatic and mode == "lock":
                chosen[key] = value
    return chosen


def resumed_preferences(state: dict, pending: dict, selection: ChoiceSelection) -> dict:
    preferred = dict(state.get("preferred_options", {}))
    for category, key, value, mode in (
        ("hotels", "hotel_evidence_id", selection.hotel_evidence_id, selection.hotel_mode),
        (
            "restaurants",
            "restaurant_evidence_ids",
            selection.restaurant_evidence_ids,
            selection.restaurant_mode,
        ),
    ):
        if pending[category]:
            preferred.pop(key, None)
            if not selection.automatic and mode == "prefer":
                preferred[key] = value
    return preferred


def planning_fingerprint(state: dict, chosen: dict, preferred: dict | None = None) -> str:
    """Ignore retrieval timestamps: an unchanged fact is not new progress."""
    facts = sorted(
        (
            e["evidence_id"],
            e["category"],
            json.dumps(
                {
                    key: value
                    for key, value in e["data"].items()
                    if not key.endswith("_at") and key not in ("retrieval_hint", "retrieval_area")
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
        )
        for e in available_evidence(state)
    )
    normalized = dict(chosen)
    if "restaurant_evidence_ids" in normalized:
        normalized["restaurant_evidence_ids"] = sorted(normalized["restaurant_evidence_ids"])
    data = {"requirements": state.get("requirements", {}), "chosen": normalized, "facts": facts}
    preferred = state.get("preferred_options", {}) if preferred is None else preferred
    if preferred:
        data["preferred"] = {
            **preferred,
            "restaurant_evidence_ids": sorted(preferred.get("restaurant_evidence_ids", [])),
        }
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def selected_constraint_issues(state: dict, itinerary: dict | None = None) -> list[ValidationIssue]:
    """Chosen constraints remain obligations even when their evidence is filtered out."""
    lookup = {e["evidence_id"]: e for e in available_evidence(state)}
    chosen = state.get("selected_options", {})
    issues = []

    def add(code, message):
        issues.append(ValidationIssue(code=code, severity="error", message=message))

    hotel = chosen.get("hotel_evidence_id")
    if hotel:
        if lookup.get(hotel, {}).get("category") != "hotel":
            add(
                "selected_hotel_unavailable",
                "你已选定的住宿已过期、不可用或缺少有效证据，需要重新确认。",
            )
        if itinerary is not None and itinerary.get("hotel_evidence_id") != hotel:
            add("selected_hotel_changed", "本轮住宿未保留你明确选择的酒店，不能作为正式行程交付。")
    food = set(chosen.get("restaurant_evidence_ids", []))
    if any(lookup.get(ref, {}).get("category") != "restaurant" for ref in food):
        add(
            "selected_restaurant_unavailable",
            "你已选定的餐厅已过期、不可用或缺少有效证据，需要重新确认。",
        )
    if food and itinerary is not None:
        meals = {
            stop["evidence_id"]
            for day in itinerary.get("days", [])
            for stop in day["stops"]
            if lookup.get(stop["evidence_id"], {}).get("category") == "restaurant"
        }
        if not meals or not meals <= food:
            add(
                "selected_restaurant_changed",
                "本轮用餐未遵守你选择的餐厅范围，不能作为正式行程交付。",
            )
    if food and itinerary is not None:
        for day in itinerary.get("days", []):
            if not any(stop["evidence_id"] in food for stop in day["stops"]):
                add(
                    "selected_daily_restaurant_missing",
                    f"{day['date']}未从明确锁定的餐厅范围安排用餐。",
                )
    # A known closure must not turn into an ordinary "source missing" warning
    # when automatic mode has no explicit chosen ID left to protect.
    for category, label in (("hotel", "住宿"), ("restaurant", "餐饮"), ("attraction", "景点")):
        if category == "hotel" and state.get("requirements", {}).get("start_date") == state.get(
            "requirements", {}
        ).get("end_date"):
            continue
        known_closed = any(
            e["category"] == category
            and e["city"] == state.get("requirements", {}).get("city")
            and unavailable_place(e["data"])
            for e in state.get("evidence", [])
        )
        if known_closed and not any(e["category"] == category for e in lookup.values()):
            add(
                f"unavailable_{category}_pool",
                f"本轮{label}候选已被来源标记为不可用，且没有有效替代，需要重新检索，不能省略后交付为已完成。",
            )
    issues.extend(anchor_issues(state.get("requirements", {}), list(lookup.values()), itinerary))
    return issues


def shortlist(evidence: list[dict], category: str, limit: int) -> list[dict]:
    groups = defaultdict(deque)
    for item in evidence:
        if (
            item["category"] == category
            and item["data"].get("name")
            and not unavailable_place(item["data"])
        ):
            groups[item["data"].get("retrieval_hint", "")].append(item)
    result, names, refs = [], set(), set()
    while groups and len(result) < limit:
        for hint in list(groups):
            queue = groups[hint]
            while queue:
                e = queue.popleft()
                name = e["data"]["name"]
                identity = re.sub(r"[（(].*?[）)]|\s+", "", name).casefold()
                if identity in names or e["evidence_id"] in refs:
                    continue
                names.add(identity)
                refs.add(e["evidence_id"])
                result.append(
                    {
                        "evidence_id": e["evidence_id"],
                        "name": name,
                        "address": e["data"].get("address", ""),
                        "retrieval_hint": hint,
                        "source": e["source"],
                        "fetched_at": e["fetched_at"],
                        "route_relation": e["data"].get("route_relation", ""),
                    }
                )
                break
            if not queue:
                del groups[hint]
            if len(result) == limit:
                break
    return result


def unavailable_selection(state: dict) -> dict:
    return {
        "pending_choice": None,
        "status": "blocked",
        "itinerary": None,
        "final_plan_md": "",
        "validation": {},
        "error_msg": "已选候选不再可用，需要重新确认",
        "reply": "选定的住宿或餐厅已过期、被来源标记为不可用，或缺少有效证据。本轮无法在保留选择的前提下继续，请更新候选或修改相关要求。",
        "trace": state.get("trace", [])
        + [
            {
                "stage": "review_options",
                "status": "blocked",
                "summary": "已选证据不可用，停止而不静默替换",
            }
        ],
    }


async def review_options(state: dict) -> dict:
    chosen = state.get("selected_options", {})
    usable = available_evidence(state)
    hotel_refs = {e["evidence_id"] for e in usable if e["category"] == "hotel"}
    food_refs = {e["evidence_id"] for e in usable if e["category"] == "restaurant"}
    missing = set()
    if chosen.get("hotel_evidence_id") and chosen["hotel_evidence_id"] not in hotel_refs:
        missing.add("hotel")
    if set(chosen.get("restaurant_evidence_ids", [])) - food_refs:
        missing.add("restaurant")
    if state.get("interaction_mode", "automatic") != "guided":
        if missing:
            return unavailable_selection(state)
        return {"pending_choice": None}
    spatial = any(
        i["code"] in ("long_transfer", "distant_hotel")
        for i in state.get("validation", {}).get("issues", [])
    )
    if (
        state.get("choice_confirmed")
        and not state.get("requested_review_categories")
        and not spatial
        and not missing
    ):
        return {"pending_choice": None}
    categories = set(state.get("review_categories", ["hotel", "restaurant"]))
    if spatial:
        categories = {"restaurant"}
        if any(i["code"] == "distant_hotel" for i in state["validation"]["issues"]):
            categories.add("hotel")
    categories |= missing
    requested = set(state.get("requested_review_categories", []))
    if requested and not spatial:
        categories = requested | missing
    if state.get("requirements", {}).get("required_hotel"):
        categories.discard("hotel")
    selected_ids = {chosen.get("hotel_evidence_id"), *chosen.get("restaurant_evidence_ids", [])}
    candidates = sorted(usable, key=lambda e: e["evidence_id"] not in selected_ids)
    hotels = shortlist(candidates, "hotel", 4) if "hotel" in categories else []
    food = shortlist(candidates, "restaurant", 6) if "restaurant" in categories else []
    if ("hotel" in missing and not hotels) or ("restaurant" in missing and not food):
        return unavailable_selection(state)
    if not hotels and not food:
        return {"pending_choice": None, "choice_confirmed": True}
    message = (
        "路线检查发现住宿或餐饮与景点距离过远。原选择已保留在候选中，请比较后重新选择；也可以说明要缩小游玩范围。周边搜索不保证有新候选。"
        if spatial
        else "先选一下住宿和餐饮，再把每天的路线安排妥当。也可以交给 Agent 自动决定。"
    )
    if missing and not spatial:
        message = "之前选定的候选已过期或未在本轮检索中返回，请重新确认相关候选后继续。"
    pending = {
        "token": uuid.uuid4().hex,
        "city": state["requirements"]["city"],
        "message": message,
        "hotels": hotels,
        "restaurants": food,
        "selected_options": state.get("selected_options", {}),
        "intent": state.get("intent", "new_trip"),
        "scope_policy_version": state.get("scope_policy_version", 0),
        "preferred_options": state.get("preferred_options", {}),
        **(
            {
                "draft_id": state["route_draft"]["draft_id"],
                "requirements_key": state["route_draft"]["requirements_key"],
                "selection_policy": "prefer_or_lock",
            }
            if state.get("route_draft")
            else {}
        ),
        "trip_summary": f"{state['requirements']['city']} · {state['requirements']['start_date']} — {state['requirements']['end_date']} · {state['requirements']['travelers']} 人",
    }
    if state.get("route_draft") and not spatial and not missing:
        message = "路线草案已在上方。可以优先考虑某些食宿，也可以明确锁定，或分别交给 Agent 安排；这些选项不代表已预订。"
        pending["message"] = message
    if spatial and state.get("spatial_repair_no_progress"):
        pending["no_progress_fingerprint"] = planning_fingerprint(state, chosen)
        pending["no_progress"] = True
        message = "本次周边搜索没有找到新的可用候选，原选择仍与路线冲突。原选择已保留；请换选其他候选、交给 Agent 放宽本次选择，或调整游玩范围。相同条件和选择不会重复计算；也可以点击“换一批候选”主动重查。"
        pending["message"] = message
        automatic = ChoiceSelection(token=pending["token"], automatic=True)
        pending["automatic_retry_blocked"] = (
            planning_fingerprint(
                state,
                resumed_constraints(state, pending, automatic),
                resumed_preferences(state, pending, automatic),
            )
            == pending["no_progress_fingerprint"]
        )
    return {
        "pending_choice": pending,
        "status": "awaiting_choice",
        "reply": message,
        "itinerary": None,
        "final_plan_md": "",
        "validation": {},
        "trace": state.get("trace", [])
        + [
            {
                "stage": "review_options",
                "summary": "已保存候选，等待用户选择后继续规划",
                "hotel_options": len(hotels),
                "restaurant_options": len(food),
            }
        ],
    }


def validate_selection(state: dict, selection: ChoiceSelection) -> dict:
    pending = state.get("pending_choice")
    if not pending or pending["token"] != selection.token:
        raise ChoiceConflict("这份选择已失效或已处理，请重新打开会话获取最新候选。")
    if pending.get("draft_id"):
        from app.graph.drafts import requirements_key

        draft = state.get("route_draft") or {}
        if draft.get("draft_id") != pending["draft_id"] or pending.get(
            "requirements_key"
        ) != requirements_key(state["requirements"]):
            raise ChoiceConflict("路线草案或需求已变更，这份选择不能用于新方案，请获取最新候选。")
    now = datetime.now(timezone.utc)
    lookup = {e["evidence_id"]: e for e in available_evidence(state)}
    valid_groups = {}
    selected_ids = {selection.hotel_evidence_id, *selection.restaurant_evidence_ids}
    for group, category in (("hotels", "hotel"), ("restaurants", "restaurant")):
        valid_groups[group] = set()
        for option in pending[group]:
            try:
                age = (now - datetime.fromisoformat(option["fetched_at"])).total_seconds()
            except (ValueError, TypeError):
                age = float("inf")
            ref = option["evidence_id"]
            available = (
                not unavailable_place(option) and lookup.get(ref, {}).get("category") == category
            )
            if ref in selected_ids:
                if not 0 <= age < 6 * 3600:
                    raise ChoiceConflict("这些候选已过期，请点击“换一批候选”重新检索后再选择。")
                if not available:
                    raise ChoiceConflict(
                        "选中的地点标注建设、装修或停业，或已缺少有效证据，请点击“换一批候选”重新检索。"
                    )
            if available and 0 <= age < 6 * 3600:
                valid_groups[group].add(ref)
    if selection.automatic:
        if selection.hotel_evidence_id or selection.restaurant_evidence_ids:
            raise ChoiceConflict("自动安排与指定候选不能同时提交。")
        if any(pending[group] and not valid_groups[group] for group in valid_groups):
            raise ChoiceConflict(
                "本次住宿或餐饮候选已全部过期或不可用，自动安排也无法跳过，请点击“换一批候选”重新检索。"
            )
    else:
        hotels, food = valid_groups["hotels"], valid_groups["restaurants"]
        if selection.hotel_mode == "automatic" and selection.hotel_evidence_id:
            raise ChoiceConflict("住宿交给 Agent 时不能同时指定酒店。")
        if selection.restaurant_mode == "automatic" and selection.restaurant_evidence_ids:
            raise ChoiceConflict("餐饮交给 Agent 时不能同时指定餐厅。")
        if (
            selection.hotel_mode != "automatic"
            and (pending["hotels"] and selection.hotel_evidence_id not in hotels)
            or (not pending["hotels"] and selection.hotel_evidence_id is not None)
        ):
            raise ChoiceConflict("请从本次住宿候选中选择一家酒店。")
        chosen_food = set(selection.restaurant_evidence_ids)
        if (
            selection.restaurant_mode != "automatic" and pending["restaurants"] and not chosen_food
        ) or not chosen_food <= food:
            raise ChoiceConflict("请从本次餐饮候选中选择 1–3 家，或交给 Agent 自动安排。")
        if len(chosen_food) != len(selection.restaurant_evidence_ids):
            raise ChoiceConflict("餐厅选择不可重复。")
        for group, mode in (
            ("hotels", selection.hotel_mode),
            ("restaurants", selection.restaurant_mode),
        ):
            if mode == "automatic" and pending[group] and not valid_groups[group]:
                raise ChoiceConflict(
                    "该类别已无可用候选，请先更新候选，不能通过自动安排跳过失效检查。"
                )
    chosen = resumed_constraints(state, pending, selection)
    preferred = resumed_preferences(state, pending, selection)
    req = state.get("requirements", {})
    if req.get("required_hotel") and chosen.get("hotel_evidence_id"):
        if not name_matches(
            req["required_hotel"],
            lookup.get(chosen["hotel_evidence_id"], {}).get("data", {}).get("name", ""),
        ):
            raise ChoiceConflict("所选酒店与明确指定酒店冲突，请先修改指定要求。")
    if chosen.get("restaurant_evidence_ids"):
        for required in req.get("required_restaurants", []):
            if not any(
                name_matches(required, lookup.get(ref, {}).get("data", {}).get("name", ""))
                for ref in chosen["restaurant_evidence_ids"]
            ):
                raise ChoiceConflict("锁定餐厅范围遗漏了明确必去餐厅，请纳入该餐厅或改为优先考虑。")
    if pending.get("no_progress_fingerprint") == planning_fingerprint(state, chosen, preferred):
        raise ChoiceConflict(
            "相同条件与选择已检查过，仍有路线冲突，未重复调用模型或地图。请换选候选、调整游玩范围，或点击“换一批候选”主动重查。"
        )
    return pending


def selection_text(state: dict, selection: ChoiceSelection) -> str:
    pending = validate_selection(state, selection)
    if selection.automatic:
        return "这些候选请交给 Agent 自动安排。"
    ids = {selection.hotel_evidence_id, *selection.restaurant_evidence_ids}
    names = [
        e["name"] for e in pending["hotels"] + pending["restaurants"] if e["evidence_id"] in ids
    ]
    if pending.get("selection_policy") == "prefer_or_lock":
        parts = []
        for group, label, mode in (
            ("hotels", "住宿", selection.hotel_mode),
            ("restaurants", "餐饮", selection.restaurant_mode),
        ):
            if not pending[group]:
                continue
            chosen_names = [e["name"] for e in pending[group] if e["evidence_id"] in ids]
            parts.append(
                f"{label}交给Agent安排"
                if mode == "automatic"
                else f"{label}{'优先考虑（可以调整）' if mode == 'prefer' else '明确采用（必须保留，全程范围）'}："
                + "、".join(chosen_names)
            )
        return "；".join(parts) + "。请继续完善路线。"
    return "我选择：" + "、".join(names) + "。请据此继续规划。"


async def apply_selection(state: dict) -> dict:
    selection = ChoiceSelection.model_validate(state["choice_selection"])
    pending = validate_selection(state, selection)
    if pending.get("scope_policy_version") != SCOPE_POLICY_VERSION:
        message = "这份候选来自旧版规划规则，尚未按当前规则确认游玩范围。本轮先不生成行程，请明确一个集中游玩的城市或区域，并确认日期；北疆等多地行程需要拆段。原日期和偏好已保留，可直接补充范围后重新检索。"
        return {
            "status": "awaiting_clarification",
            "reply": message,
            "pending_choice": None,
            "choice_selection": None,
            "itinerary": None,
            "final_plan_md": "",
            "validation": {},
            "trace": state.get("trace", [])
            + [
                {
                    "stage": "apply_selection",
                    "status": "awaiting_clarification",
                    "summary": "旧候选缺少范围策略版本，先确认范围，不调用规划模型",
                }
            ],
        }
    chosen = resumed_constraints(state, pending, selection)
    return {
        "intent": pending.get("intent", "new_trip"),
        "previous_itinerary": state.get("accepted_plan", {}).get("itinerary"),
        "selected_options": chosen,
        "preferred_options": resumed_preferences(state, pending, selection),
        **({"planning_strategy": "legacy"} if not pending.get("draft_id") else {}),
        "choice_confirmed": True,
        "choice_selection": None,
        "pending_choice": None,
        "status": "planning",
        "reply": "",
        "validation": {},
        "spatial_repair_no_progress": False,
        "trace": state.get("trace", [])
        + [
            {
                "stage": "apply_selection",
                "summary": "用户授权自动安排"
                if selection.automatic
                else "用户已选择，作为规划约束继续",
                "selected_options": chosen,
            }
        ],
    }


def after_review(state: dict) -> str:
    return "deliver" if state.get("pending_choice") or state.get("status") == "blocked" else "plan"


def planner_evidence(state: dict) -> list[dict]:
    chosen = state.get("selected_options", {})
    hotel, food = chosen.get("hotel_evidence_id"), chosen.get("restaurant_evidence_ids", [])
    return [
        e
        for e in available_evidence(state)
        if not unavailable_place(e["data"])
        and not (e["category"] == "hotel" and hotel and e["evidence_id"] != hotel)
        and not (e["category"] == "restaurant" and food and e["evidence_id"] not in food)
    ]
