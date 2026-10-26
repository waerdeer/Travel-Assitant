"""A provisional route has its own contract and never becomes an accepted plan."""

import hashlib
import json
import uuid
from datetime import date, timedelta

from app.graph.anchors import anchor_issues, name_matches
from app.graph.choices import available_evidence
from app.graph.geography import enrich_locations
from app.graph.research import model_evidence
from app.graph.schedule import day_schedule, needs_attractions, schedules
from app.graph.validation import distance_km
from app.schemas.planning import Requirements, RouteDraft
from app.services.model_gateway import ask_json


def requirements_key(requirements: dict) -> str:
    normalized = Requirements.model_validate(requirements).model_dump()
    # Preserve hashes of existing pending drafts when new optional scheduling
    # fields contain only their defaults. Real availability changes still invalidate.
    for key, default in {
        "arrival_time": None,
        "departure_time": None,
        "arrival_buffer_minutes": 60,
        "departure_buffer_minutes": 90,
        "rest_dates": [],
    }.items():
        if normalized[key] == default:
            normalized.pop(key)
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def check_draft(
    draft: dict, requirements: dict, evidence: list[dict]
) -> tuple[list[str], list[str]]:
    req = Requirements.model_validate(requirements)
    lookup = {e["evidence_id"]: e for e in evidence}
    errors = [i.message for i in anchor_issues(requirements, evidence)]
    warnings = []
    expected = [
        (date.fromisoformat(req.start_date) + timedelta(days=i)).isoformat()
        for i in range(
            (date.fromisoformat(req.end_date) - date.fromisoformat(req.start_date)).days + 1
        )
    ]
    if draft["city"] != req.city or [str(d["date"]) for d in draft["days"]] != expected:
        errors.append("草案目的地或日期覆盖不符合本次需求。")
    seen, names = set(), []
    cap = min(
        req.daily_attraction_limit or 5, {"relaxed": 2, "balanced": 3, "intensive": 5}[req.pace]
    )
    for day in draft["days"]:
        refs = day["attraction_evidence_ids"]
        window = day_schedule(req, str(day["date"]))
        if (not refs and window["requires_attraction"]) or len(refs) > cap:
            errors.append("草案每日主要活动数量不符合节奏要求。")
        if refs and window["rest"]:
            errors.append("用户明确休息或只入住的日期不能安排景点。")
        previous = None
        for ref in refs:
            place = lookup.get(ref)
            if not place or place["category"] != "attraction":
                errors.append("草案含缺少有效同城证据的主要活动，不能展示。")
                continue
            if ref in seen:
                errors.append("草案重复安排同一景点，不能靠重复凑天数。")
            seen.add(ref)
            names.append(place["data"].get("name", ""))
            if not place["data"].get("location"):
                warnings.append("部分主要活动缺坐标，区域关系尚未核实。")
            if previous:
                km = distance_km(previous["data"], place["data"])
                if km is not None and km > 30:
                    warnings.append(
                        f"{day['date']} 的主要活动直线距离约{km:.1f}km，存在跨区风险，需要后续调整。"
                    )
            previous = place
    anchors = [
        e
        for e in evidence
        if (
            e["category"] == "hotel"
            and name_matches(req.required_hotel, e["data"].get("name", ""))
            or e["category"] == "restaurant"
            and any(
                name_matches(name, e["data"].get("name", "")) for name in req.required_restaurants
            )
        )
    ]
    activities = [lookup[ref] for ref in seen if ref in lookup]
    for anchor in anchors:
        label = "指定酒店" if anchor["category"] == "hotel" else "必去餐厅"
        name = anchor["data"].get("name", "")
        distances = [distance_km(anchor["data"], place["data"]) for place in activities]
        if not distances or any(km is None for km in distances):
            warnings.append(f"{label}「{name}」与部分主要活动缺坐标，往返关系尚未核实。")
        known = [km for km in distances if km is not None]
        far = max(known, default=0) if anchor["category"] == "hotel" else min(known, default=0)
        if far > 30:
            warnings.append(
                f"{label}「{name}」与主要活动直线距离约{far:.1f}km，存在跨区风险；保留指定地点，后续需调整路线，不能静默换店。"
            )
    for required in req.must_visit:
        if not any(required in name for name in names):
            errors.append(f"草案遗漏必去景点「{required}」。")
    for excluded in req.avoid_places:
        if any(excluded in name for name in names):
            errors.append(f"草案包含排除景点「{excluded}」。")
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))


def failed_draft(state: dict, message: str, *, status: str = "blocked", metrics=None) -> dict:
    return {
        "route_draft": None,
        "status": status,
        "reply": message,
        "itinerary": None,
        "final_plan_md": "",
        "validation": {},
        "metrics": metrics if metrics is not None else state.get("metrics", {}),
        "trace": state.get("trace", [])
        + [{"stage": "draft_route", "status": status, "summary": message}],
    }


async def build_route_draft(state: dict) -> dict:
    req = Requirements.model_validate(state["requirements"])
    evidence = available_evidence(state)
    issues = anchor_issues(state["requirements"], evidence)
    if issues:
        return failed_draft(
            state,
            "\n".join(i.message for i in issues),
            status="awaiting_clarification"
            if any(i.code.endswith("ambiguous") for i in issues)
            else "blocked",
        )
    if needs_attractions(req) and not any(e["category"] == "attraction" for e in evidence):
        return failed_draft(state, "没有可用的景点证据，暂时无法形成有来源的路线草案。")
    metrics = dict(state.get("metrics", {}))
    try:
        previous = state.get("previous_itinerary")
        if state.get("intent") == "modify_hotel" and previous:
            draft = RouteDraft(
                city=previous["city"],
                days=[
                    {
                        "date": d["date"],
                        "theme": d["theme"],
                        "attraction_evidence_ids": [
                            s["evidence_id"]
                            for s in d["stops"]
                            if any(
                                e["evidence_id"] == s["evidence_id"]
                                and e["category"] == "attraction"
                                for e in evidence
                            )
                        ],
                    }
                    for d in previous["days"]
                ],
                rationale="本次仅比较住宿，沿用已保存的每日主要活动。",
            )
        else:
            cap = min(
                req.daily_attraction_limit or 5,
                {"relaxed": 2, "balanced": 3, "intensive": 5}[req.pace],
            )
            feedback, current = [], None
            for attempt in range(2):
                draft, usage = await ask_json(
                    RouteDraft,
                    f"先生成路线草案，不安排普通酒店和餐厅，不生成时刻表或价格。只用同城有效attraction证据ID，日期完整有序。普通游玩日至少1处、最多{cap}处景点且全程不重复，遵守必去及排除。"
                    "daily_schedule中rest=true必须空景点；requires_attraction=false的短时抵离日允许空景点，theme说明入住休息/返程安排。不能自行把普通日改为空日。"
                    "明确酒店/餐厅锚点参与主要活动选择，其他食宿后补。rationale说明主要区域与取舍，不得声称真实导航、营业或预约已核实，不得新增证据外地名。"
                    "有validation_feedback时修正上一份草案；不得用删除日期或虚构ID绕过限制。rationale面向旅行用户用自然中文，不提schema、attraction、证据ID或内部字段。",
                    {
                        "requirements": state["requirements"],
                        "daily_schedule": schedules(req),
                        "daily_attraction_cap": cap,
                        "evidence": model_evidence(evidence),
                        "previous_itinerary": previous,
                        "current_draft": current,
                        "validation_feedback": feedback,
                    },
                )
                for key in ("model_calls", "input_tokens", "output_tokens"):
                    metrics[key] = metrics.get(key, 0) + usage.get(key, 0)
                if attempt:
                    metrics["draft_repairs"] = metrics.get("draft_repairs", 0) + 1
                current = draft.model_dump(mode="json")
                feedback, _ = check_draft(current, state["requirements"], evidence)
                if not feedback:
                    break
        data = draft.model_dump(mode="json")
        errors, warnings = check_draft(data, state["requirements"], evidence)
        if errors:
            return failed_draft(
                state, "路线草案暂未满足基本约束：\n" + "\n".join(errors), metrics=metrics
            )
        data.update(
            draft_id=uuid.uuid4().hex,
            run_id=state.get("run_id", ""),
            requirements_key=requirements_key(state["requirements"]),
            status="draft",
            warnings=warnings,
            checked=["目的地与日期覆盖", "主要活动证据引用", "景点数量与必去排除"],
            unchecked=["真实导航与交通时间", "营业与预约", "住宿与餐饮", "完整预算"],
            evidence=evidence,
            requirements=req.model_dump(),
        )
        return {
            "route_draft": data,
            "status": "planning",
            "metrics": metrics,
            "trace": state.get("trace", [])
            + [
                {
                    "stage": "draft_route",
                    "summary": "路线草案已形成，先展示主要活动，再补充食宿",
                    "draft_id": data["draft_id"],
                }
            ],
        }
    except Exception as exc:
        for key, value in getattr(exc, "usage", {}).items():
            metrics[key] = metrics.get(key, 0) + value
        return failed_draft(
            state,
            "路线草案未能生成有效结果，请稍后重试或调整需求。",
            status="failed",
            metrics=metrics,
        )


async def enrich_route_draft(state: dict) -> dict:
    draft = state["route_draft"]
    evidence = available_evidence(state)
    req = state["requirements"]
    extra = [
        e["evidence_id"]
        for e in evidence
        if (
            e["category"] == "hotel"
            and name_matches(req.get("required_hotel", ""), e["data"].get("name", ""))
            or e["category"] == "restaurant"
            and any(
                name_matches(name, e["data"].get("name", ""))
                for name in req.get("required_restaurants", [])
            )
        )
    ]
    pseudo = {
        "days": [
            {"stops": [{"evidence_id": ref} for ref in d["attraction_evidence_ids"]]}
            for d in draft["days"]
        ]
    }
    if extra:
        pseudo["days"][0]["stops"] += [{"evidence_id": ref} for ref in extra]
    update = await enrich_locations({**state, "itinerary": pseudo})
    combined = {**state, **update}
    errors, warnings = check_draft(draft, state["requirements"], available_evidence(combined))
    if errors:
        return {
            **update,
            **failed_draft(combined, "补充详情后发现草案地点不可用：\n" + "\n".join(errors)),
        }
    return {
        **update,
        "route_draft": {**draft, "warnings": warnings, "evidence": available_evidence(combined)},
    }
