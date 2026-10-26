"""Deterministic acceptance criteria. No model judges its own output here."""

from datetime import date, timedelta
from math import asin, ceil, cos, radians, sin, sqrt

from app.graph.schedule import day_schedule
from app.schemas.planning import (
    Evidence,
    Itinerary,
    Requirements,
    ValidationIssue,
    ValidationReport,
)


def requirement_problems(req: Requirements) -> list[str]:
    problems = []
    if not req.city.strip():
        problems.append("想去哪个国内城市？第一版支持单城市旅行。")
    dates = []
    for label, value in (("出发", req.start_date), ("返程", req.end_date)):
        if label == "返程" and not value and req.duration_days and not req.start_date:
            continue
        try:
            dates.append(date.fromisoformat(value))
        except ValueError:
            problems.append(f"请提供{label}日期（YYYY-MM-DD）。")
    if len(dates) == 2:
        span = (dates[1] - dates[0]).days + 1
        if not 1 <= span <= 14:
            problems.append("请把返程日期设为出发当天至第 14 天之间。")
        elif req.duration_days and req.duration_days != span:
            problems.append(f"日期对应 {span} 天，与要求的 {req.duration_days} 天不一致，请确认。")
        if (
            dates[0] == dates[1]
            and req.arrival_time
            and req.departure_time
            and minutes(req.arrival_time) >= minutes(req.departure_time)
        ):
            problems.append("同日离开时刻必须晚于抵达时刻，请确认抵离时间或日期。")
        for value in req.rest_dates:
            try:
                rest = date.fromisoformat(value)
            except ValueError:
                problems.append("休息日期须为 YYYY-MM-DD。")
                continue
            if not dates[0] <= rest <= dates[1]:
                problems.append(f"休息日期 {value} 不在旅行日期内，请确认。")
    return problems


def minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def distance_km(a: dict, b: dict) -> float | None:
    """Straight-line distance only; never a road-route/time guarantee."""
    try:
        lon1, lat1 = map(float, a["location"].split(","))
        lon2, lat2 = map(float, b["location"].split(","))
        if not all(
            (-180 <= lon <= 180 and -90 <= lat <= 90) for lon, lat in ((lon1, lat1), (lon2, lat2))
        ):
            return None
        lat1, lat2 = radians(lat1), radians(lat2)
        x = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin(radians(lon2 - lon1) / 2) ** 2
        return 6371 * 2 * asin(sqrt(min(1, max(0, x))))
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def validate_itinerary(
    plan: Itinerary, req: Requirements, evidence: list[Evidence]
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    checks = [
        "目的地一致",
        "日期覆盖",
        "地点证据引用",
        "每日时间与节奏",
        "人均预算",
        "住宿与餐饮",
        "天气覆盖",
        "地理距离",
        "必去与排除地点",
    ]
    lookup = {e.evidence_id: e for e in evidence if e.city == req.city}

    def add(code, message, day=None, severity="error"):
        issues.append(ValidationIssue(code=code, severity=severity, message=message, day=day))

    for problem in requirement_problems(req):
        add("requirements_invalid", problem)

    def check_transfer(first, second, previous_end, begin, day):
        nonlocal missing_coords
        km = distance_km(first.data, second.data)
        if km is None:
            missing_coords = True
            return
        gap = begin - previous_end
        if first.evidence_id == second.evidence_id:
            return
        names = f"「{first.data.get('name', '')}」→「{second.data.get('name', '')}」"
        if km > 30:
            minimum = ceil(km / 25 * 60) + 15
            if gap < minimum:
                code = (
                    "long_attraction_transfer"
                    if first.category == second.category == "attraction"
                    else "long_transfer"
                )
                add(
                    code,
                    f"{names}直线距离约{km:.1f}km，仅留白{gap}分钟，低于排程粗筛约{minimum}分钟；需重排相应地点或时段（非导航时间）。",
                    day,
                )
            else:
                add(
                    "long_transfer_unverified",
                    f"{names}直线距离约{km:.1f}km，已预留{gap}分钟，但真实交通路线与耗时尚待核实。",
                    day,
                    severity="warning",
                )
        elif gap < max(15, int(km / 25 * 60)):
            add("transfer_buffer", f"{names}交通留白不足（按直线距离保守检查，非导航时间）。", day)

    if plan.city != req.city:
        add("city_mismatch", "行程城市必须与用户需求一致。")
    start, end = date.fromisoformat(req.start_date), date.fromisoformat(req.end_date)
    expected = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if [d.date for d in plan.days] != expected:
        add(
            "date_coverage",
            "每日日期必须按顺序完整覆盖出发日至返程日，不得重复或遗漏。",
        )
    visited = set()
    has_restaurant = False
    missing_coords = False
    for day in plan.days:
        tag = day.date.isoformat()
        window = day_schedule(req, tag)
        previous_end, previous_item = None, None
        attractions = 0
        daily_meal = False
        for stop in day.stops:
            item = lookup.get(stop.evidence_id)
            begin, finish = minutes(stop.start_time), minutes(stop.end_time)
            if begin < window["start_minute"] or finish > window["end_minute"]:
                add("availability_window", "活动超出抵离接驳后的可用时段。", tag)
            if not item or item.category not in ("attraction", "restaurant"):
                add(
                    "invalid_reference",
                    f"地点引用 {stop.evidence_id} 必须指向真实景点或餐厅。",
                    tag,
                )
            else:
                has_restaurant |= item.category == "restaurant"
                daily_meal |= item.category == "restaurant"
                if item.category == "attraction":
                    attractions += 1
                    if stop.evidence_id in visited:
                        add(
                            "duplicate_attraction",
                            f"景点 {item.data.get('name')} 被重复安排。",
                            tag,
                        )
                    visited.add(stop.evidence_id)
                if previous_item and previous_end is not None:
                    check_transfer(previous_item, item, previous_end, begin, tag)
                previous_item = item
            if begin < 8 * 60 or finish > 21 * 60 or finish - begin < 30:
                add("time_window", "活动须安排在 08:00–21:00，且每项至少 30 分钟。", tag)
            if previous_end is not None and begin < previous_end:
                add("time_overlap", "同一天活动时间重叠或顺序错误。", tag)
            previous_end = finish
        if window["rest"] and attractions:
            add("rest_day_activity", "用户要求当天只入住或休息，不得安排景点。", tag)
        if not attractions and window["requires_attraction"]:
            add("missing_attraction", "每天至少安排一个已检索的景点。", tag)
        daily_refs = {
            stop.evidence_id
            for stop in day.stops
            if lookup.get(stop.evidence_id) and lookup[stop.evidence_id].category == "attraction"
        }
        flexible = []
        for meal in day.meal_breaks:
            anchor = lookup.get(meal.anchor_evidence_id)
            if meal.anchor_evidence_id not in daily_refs or not anchor:
                add(
                    "invalid_meal_anchor",
                    "自由用餐区域必须引用当日有来源的景点，不能借用其他日期或外部地点。",
                    tag,
                )
                continue
            begin, finish = minutes(meal.start_time), minutes(meal.end_time)
            if begin < window["start_minute"] or finish > window["end_minute"]:
                add("availability_window", "自由用餐超出抵离接驳后的可用时段。", tag)
            if begin < 8 * 60 or finish > 21 * 60 or finish - begin < 30:
                add("meal_time_window", "自由用餐须在08:00–21:00内至少预留30分钟。", tag)
            flexible.append((begin, finish, anchor, True))
        if flexible:
            scheduled = flexible + [
                (minutes(stop.start_time), minutes(stop.end_time), lookup[stop.evidence_id], False)
                for stop in day.stops
                if stop.evidence_id in lookup
            ]
            scheduled.sort(key=lambda item: item[0])
            for first, second in zip(scheduled, scheduled[1:]):
                if first[3] or second[3]:
                    if second[0] < first[1]:
                        add("meal_time_overlap", "自由用餐与活动时间重叠。", tag)
                    else:
                        check_transfer(first[2], second[2], first[1], second[0], tag)
        if (
            not daily_meal
            and not flexible
            and window["requires_attraction"]
            and (
                plan.service_mode == "browse"
                or any(e.category == "restaurant" for e in lookup.values())
            )
        ):
            add("missing_daily_meal", "每天需要具体餐饮或有明确时段的自由用餐留白。", tag)
        if day.stay_anchor_evidence_id and day.stay_anchor_evidence_id not in daily_refs:
            add("invalid_stay_anchor", "住宿建议区域必须以当日有来源的景点为参照。", tag)
        if (
            plan.service_mode == "browse"
            and day.date != expected[-1]
            and not plan.hotel_evidence_id
            and not day.stay_anchor_evidence_id
            and window["requires_attraction"]
        ):
            add(
                "missing_stay_area",
                "非返程日需要建议住宿区域（当日景点为参照），无需指定酒店。",
                tag,
            )
        cap = min(
            req.daily_attraction_limit or 5, {"relaxed": 2, "balanced": 3, "intensive": 5}[req.pace]
        )
        if attractions > cap:
            add("pace_limit", f"景点数量超过用户节奏要求（每天最多 {cap} 个）。", tag)

    hotels = [e for e in lookup.values() if e.category == "hotel"]
    visited_names = [lookup[ref].data.get("name", "") for ref in visited]
    for required in req.must_visit:
        if not any(required in name for name in visited_names):
            add(
                "must_visit_missing",
                f"必去地点「{required}」未安排；若未检索到须调整需求，不能自行编造。",
            )
    for excluded in req.avoid_places:
        if any(excluded in name for name in visited_names):
            add("excluded_place", f"行程安排了用户排除的「{excluded}」。")
    restaurants = [e for e in lookup.values() if e.category == "restaurant"]
    hotel = lookup.get(plan.hotel_evidence_id or "")
    if plan.hotel_evidence_id and (not hotel or hotel.category != "hotel"):
        add("invalid_hotel", "住宿必须引用检索到的酒店。")
    if hotel and hotel.category == "hotel":
        for day in plan.days:
            activities = [
                stop
                for stop in day.stops
                if lookup.get(stop.evidence_id)
                and lookup[stop.evidence_id].category == "attraction"
            ]
            if not activities:
                continue
            for stop in (activities[0], activities[-1]):
                place = lookup.get(stop.evidence_id)
                km = distance_km(hotel.data, place.data) if place else None
                if km is None:
                    missing_coords = True
                elif km > 30:
                    add(
                        "distant_hotel",
                        f"「{hotel.data.get('name', '')}」到「{place.data.get('name', '')}」直线距离约{km:.1f}km，有较长往返通勤风险；已保留住宿，需核实交通方式与真实耗时。",
                        day.date.isoformat(),
                        severity="warning",
                    )
    if plan.service_mode != "browse" and len(expected) > 1 and not hotel:
        add(
            "missing_hotel",
            "多日行程未选住宿。",
            severity="error" if hotels else "warning",
        )
    if plan.service_mode != "browse" and not has_restaurant:
        add(
            "missing_meal",
            "未安排有来源的餐厅。",
            severity="error" if restaurants else "warning",
        )
    if len(expected) > 1 and plan.costs.accommodation <= 0:
        add("missing_hotel_cost", "多日旅行必须预留住宿估算。")
    if plan.costs.meals <= 0 or plan.costs.transport <= 0:
        add("missing_costs", "餐饮和市内交通必须预留费用估算。")
    if req.budget_per_person and plan.costs.total > req.budget_per_person:
        add(
            "budget_exceeded",
            f"人均估算 ¥{plan.costs.total:g} 超过预算 ¥{req.budget_per_person:g}，须减少支出或说明不可行。",
        )
    dates = {str(e.data.get("date")) for e in lookup.values() if e.category == "weather"}
    if not {d.isoformat() for d in expected} <= dates:
        add(
            "weather_uncovered",
            "近期天气预报未覆盖全部旅行日期，不可把近期天气当作出行当天预报。",
            severity="warning",
        )
    if missing_coords:
        add(
            "coordinates_missing",
            "部分地点无坐标，无法核验其距离；出行前请通过地图核实。",
            severity="warning",
        )
    if req.arrival_time or req.departure_time:
        add(
            "arrival_departure_assumptions",
            "抵离时刻来自用户；接驳留白为规划假设，尚未核实机场/车站、交通路线与办理手续耗时。",
            severity="warning",
        )
    add(
        "estimates_only",
        "费用、交通时长和开放情况尚未经过实时价格／导航／营业时间接口核验。",
        severity="warning",
    )
    unverified = []
    if req.arrival_time or req.departure_time:
        unverified.append("抵离接驳与办理手续耗时")
    if any(i.code in ("long_transfer_unverified", "distant_hotel") for i in issues):
        unverified.append("跨区交通与住宿往返")
    if missing_coords:
        unverified.append("地理距离")
    if not {d.isoformat() for d in expected} <= dates:
        unverified.append("天气覆盖")
    return ValidationReport(
        passed=not any(i.severity == "error" for i in issues),
        issues=issues,
        checks=[c for c in checks if c not in unverified],
        unverified_checks=unverified,
    )
