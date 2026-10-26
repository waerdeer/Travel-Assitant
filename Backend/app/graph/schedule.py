"""User availability is independent of generated days and cannot be waived by a plan."""

import re
from datetime import date, timedelta

from app.schemas.planning import Requirements


def minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def clock(value: int) -> str:
    value = min(1439, max(0, value))
    return f"{value // 60:02d}:{value % 60:02d}"


def day_schedule(req: Requirements, day: str) -> dict:
    start, end = 8 * 60, 21 * 60
    assumptions = []
    current = date.fromisoformat(day)
    if req.arrival_time:
        arrival_bound = (
            minutes(req.arrival_time)
            + req.arrival_buffer_minutes
            - (current - date.fromisoformat(req.start_date)).days * 1440
        )
    else:
        arrival_bound = 0
    if req.arrival_time and (day == req.start_date or arrival_bound > start):
        start = max(start, arrival_bound)
        assumptions.append(f"{req.arrival_time}抵达，之后预留{req.arrival_buffer_minutes}分钟接驳")
    if req.departure_time:
        departure_bound = (
            (date.fromisoformat(req.end_date) - current).days * 1440
            + minutes(req.departure_time)
            - req.departure_buffer_minutes
        )
    else:
        departure_bound = 1440
    if req.departure_time and (day == req.end_date or departure_bound < end):
        end = min(end, departure_bound)
        assumptions.append(
            f"{req.departure_time}离开，之前预留{req.departure_buffer_minutes}分钟接驳"
        )
    rest = day in req.rest_dates
    # Only the user requirements can excuse a day. A generated empty day is not evidence.
    short = bool(assumptions) and end - start < 180
    return {
        "date": day,
        "start_minute": start,
        "end_minute": end,
        "start_time": clock(start),
        "end_time": clock(end),
        "has_time": end > start,
        "requires_attraction": not rest and not short,
        "rest": rest,
        "note": "；".join(assumptions),
    }


def schedules(req: Requirements) -> list[dict]:
    start, end = date.fromisoformat(req.start_date), date.fromisoformat(req.end_date)
    return [
        day_schedule(req, (start + timedelta(days=i)).isoformat())
        for i in range((end - start).days + 1)
    ]


def needs_attractions(req: Requirements) -> bool:
    return any(day["requires_attraction"] for day in schedules(req)) or bool(req.must_visit)


def preserve_schedule(
    previous: dict, proposed: Requirements, *, fresh: bool, releases=(), text=""
) -> list[str]:
    """Omitted times survive follow-up edits; explicit new times replace their side only.

    Rest dates survive only if still within the same trip's date range.
    """
    if fresh:
        return []
    for key in ("arrival_time", "departure_time"):
        if getattr(proposed, key) is None and previous.get(key):
            setattr(proposed, key, previous[key])
            buffer = key.replace("_time", "_buffer_minutes")
            default = 60 if key == "arrival_time" else 90
            if getattr(proposed, buffer) == default:
                setattr(proposed, buffer, previous.get(buffer, default))
    proposed.rest_dates = sorted(
        set(proposed.rest_dates)
        | {
            value
            for value in previous.get("rest_dates", [])
            if proposed.start_date <= value <= proposed.end_date
        }
    )
    questions = []
    for change in releases:
        quote = change.user_quote.strip()
        clauses = {part.strip() for part in re.split(r"[，,。；;！!\n]", text) if part.strip()}
        label = {
            "arrival_time": r"(?:抵达|到达)(?:时间|时刻)(?:限制|要求|约束)?",
            "departure_time": r"(?:返程|离开|回程)(?:时间|时刻)(?:限制|要求|约束)?",
            "rest_date": r"(?:整天)?休息(?:日)?(?:安排|要求|限制)?",
        }[change.target]
        uncertain = re.search(
            r"[？?]|吗|么|呢|是否|能否|可否|能不能|要不要|如果|假如|假设|先别|不要|不取消|不解除|不去掉|暂不|先不|不想|不打算|不能|没(?:有)?(?:说|要|让)|不是|并非|举例|例子|不执行|别执行|保留|保持|照旧|不变",
            text,
        )
        if change.target == "rest_date":
            # Bind the date to the cancellation action itself, never to a
            # different retained date mentioned elsewhere in the quoted sentence.
            scope = re.escape(change.rest_date) if change.rest_date else r"(?:全部|所有)"
            label = scope + label
        valid = (
            quote.rstrip("。！!") in clauses
            and not uncertain
            and re.fullmatch(
                r"(?:请|我想|我要|帮我)?(?:取消|解除|去掉)(?:原来|之前)?" + label + r"[。！!]?",
                quote,
            )
        )
        if not valid:
            questions.append(
                "已保留原抵离/休息要求；如需取消，请明确说明取消哪项时间限制或哪一天休息安排。"
            )
            continue
        if change.target == "rest_date":
            proposed.rest_dates = [
                value
                for value in proposed.rest_dates
                if change.rest_date and value != change.rest_date
            ]
        else:
            setattr(proposed, change.target, None)
    return list(dict.fromkeys(questions))
