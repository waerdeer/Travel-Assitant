"""Deterministic delivery: structured reference IDs become sourced place names."""

from html import escape
from urllib.parse import quote

from app.graph.schedule import day_schedule
from app.schemas.planning import Evidence, Itinerary, Requirements, ValidationReport


def text(value: str) -> str:
    return (
        escape(str(value))
        .replace("\n", " ")
        .replace("|", "／")
        .replace("[", "［")
        .replace("]", "］")
    )


def render_plan(
    plan: Itinerary,
    req: Requirements,
    evidence: list[Evidence],
    report: ValidationReport,
) -> str:
    lookup = {e.evidence_id: e for e in evidence}
    lines = [
        f"# {text(plan.city)} · {len(plan.days)} 日旅行",
        "",
        f"{req.start_date} — {req.end_date} · {req.travelers} 人 · 人均预算 "
        + (f"¥{req.budget_per_person:g}" if req.budget_per_person else "未设定"),
        "",
    ]
    warnings = [i.message for i in report.issues if i.severity == "warning"]
    if warnings:
        lines += [
            "> **出行前须知**：" + "；".join(text(w).rstrip("。；") for w in warnings) + "。",
            "",
        ]
    for index, day in enumerate(plan.days, 1):
        window = day_schedule(req, day.date.isoformat())
        lines += [
            f"## Day {index} · {day.date.isoformat()}",
            f"**{text(day.theme)}**",
            "",
        ]
        if window["note"]:
            lines += [f"抵离安排：{text(window['note'])}（接驳为规划假设，非导航结果）。", ""]
            lines += [
                f"可安排活动时段：{window['start_time']}–{window['end_time']}。"
                if window["has_time"]
                else "接驳后没有可安排的游玩时段，仅处理入住或返程。",
                "",
            ]
        if not day.stops:
            lines += [
                "当天按用户要求休息，不安排景点。"
                if window["rest"]
                else "当天抵离可用时间有限，预留入住休息或返程，不强行安排景点。",
                "",
            ]
            if day.date.isoformat() != req.end_date and not plan.hotel_evidence_id:
                lines += ["住宿区域待定，请按已订住宿入住或另行确认；未预订酒店。", ""]
        timeline = [(stop.start_time, "stop", stop) for stop in day.stops] + [
            (meal.start_time, "meal", meal) for meal in day.meal_breaks
        ]
        for _, kind, stop in sorted(timeline, key=lambda item: item[0]):
            if kind == "meal":
                anchor = lookup[stop.anchor_evidence_id]
                lines.append(
                    f"- **{stop.start_time}–{stop.end_time} · 自由用餐**：以「{text(anchor.data.get('name', ''))}」周边为参照，餐厅待按需浏览选择，未预订。"
                )
                continue
            place = lookup[stop.evidence_id]
            name, address = (
                text(place.data.get("name", "")),
                text(place.data.get("address", "")),
            )
            url = (
                "https://uri.amap.com/search?keyword="
                + quote(place.data.get("name", ""))
                + "&city="
                + quote(req.city)
            )
            lines += [
                f"- **{stop.start_time}–{stop.end_time} · [{name}]({url})**",
                f"  {address}",
            ]
            if stop.note:
                lines.append(f"  规划建议（模型生成）：{text(stop.note)}")
        if day.stay_anchor_evidence_id and not plan.hotel_evidence_id:
            anchor = lookup[day.stay_anchor_evidence_id]
            lines.append(
                f"住宿建议区域：以「{text(anchor.data.get('name', ''))}」周边为检索参照，具体酒店待浏览，实际通勤与房态待确认。"
            )
        lines.append("")
    if plan.hotel_evidence_id:
        hotel = lookup[plan.hotel_evidence_id]
        lines += [
            "## 住宿候选",
            f"**{text(hotel.data['name'])}** · {text(hotel.data.get('address', ''))}",
            "仅为地图检索候选，未预订；房价、房态及是否符合住宿偏好需另行核实。",
            "",
        ]
    lines += [
        "## 费用估算",
        "全程人均人民币估算，非实时价格；不含往返目的地的大交通。",
        "",
        "| 类别 | 人均估算 |",
        "| --- | ---: |",
        f"| 住宿 | ¥{plan.costs.accommodation:g} |",
        f"| 餐饮 | ¥{plan.costs.meals:g} |",
        f"| 市内交通 | ¥{plan.costs.transport:g} |",
        f"| 门票 | ¥{plan.costs.tickets:g} |",
        f"| 合计 | **¥{plan.costs.total:g}** |",
        "",
        f"估算依据：{text(plan.costs.basis)}",
        "",
    ]
    if plan.suggestions:
        lines += ["## 旅行提示"] + [f"- {text(s)}" for s in plan.suggestions] + [""]
    used = {s.evidence_id for d in plan.days for s in d.stops}
    if plan.hotel_evidence_id:
        used.add(plan.hotel_evidence_id)
    lines += [
        "## 数据来源",
        "地点来自高德地图 MCP，以下为检索时间；文字建议与费用由模型生成。",
    ]
    for ref in sorted(used):
        e = lookup[ref]
        lines.append(f"- {text(e.data.get('name', ''))} · {e.fetched_at} · `{ref}`")
    return "\n".join(lines)
