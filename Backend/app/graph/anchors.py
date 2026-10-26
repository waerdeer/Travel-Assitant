"""Explicit user anchors are required once; they are not exclusive restaurant pools."""

import re

from app.schemas.planning import ValidationIssue


def name_matches(required: str, actual: str) -> bool:
    def normalize(value):
        return re.sub(r"[\s（）()·]", "", value).casefold()

    return bool(required.strip()) and normalize(required) in normalize(actual)


def anchor_issues(
    requirements: dict, evidence: list[dict], itinerary: dict | None = None
) -> list[ValidationIssue]:
    issues = []
    hotel_name = requirements.get("required_hotel", "")
    hotels = [
        e
        for e in evidence
        if e["category"] == "hotel" and name_matches(hotel_name, e["data"].get("name", ""))
    ]

    def add(code, message):
        issues.append(ValidationIssue(code=code, severity="error", message=message))

    if hotel_name:
        if not hotels:
            add(
                "required_hotel_missing",
                f"指定酒店「{hotel_name}」没有可用的同城证据，需确认完整店名、地址或可用状态，不能自行换店。",
            )
        elif len(hotels) > 1:
            add(
                "required_hotel_ambiguous",
                f"指定酒店「{hotel_name}」匹配多家门店，请补充完整店名或地址。",
            )
        elif (
            itinerary is not None and itinerary.get("hotel_evidence_id") != hotels[0]["evidence_id"]
        ):
            add("required_hotel_changed", f"本轮没有保留指定酒店「{hotel_name}」。")
    used = {s["evidence_id"] for day in (itinerary or {}).get("days", []) for s in day["stops"]}
    for required in requirements.get("required_restaurants", []):
        matching = [
            e
            for e in evidence
            if e["category"] == "restaurant" and name_matches(required, e["data"].get("name", ""))
        ]
        if not matching:
            add(
                "required_restaurant_unavailable",
                f"必去餐厅「{required}」没有可用的同城证据，不能改成其他店。",
            )
        elif itinerary is not None and not any(e["evidence_id"] in used for e in matching):
            add(
                "required_restaurant_omitted", f"本轮遗漏必去餐厅「{required}」，至少需要安排一次。"
            )
    return issues


def same_city(left: str, right: str) -> bool:
    """Only the optional city suffix is an alias; regions are never collapsed."""

    def normalize(value):
        return re.sub(r"\s+", "", value).removesuffix("市")

    return bool(left and right) and normalize(left) == normalize(right)


def preserve_anchors(
    previous: dict, proposed, changes: list, text: str, reset_quote: str = ""
) -> list[str]:
    """Merge obligations; only an affirmative full clause can release a named target.

    Quotes locate the request, but are never treated as authorization on their
    own: a model can accidentally quote '取消H' from '不要取消H'. Unsupported
    expressions retain the obligation and request clarification.
    """
    if not previous or not same_city(previous.get("city", ""), proposed.city):
        return []
    # Inspect the whole request before splitting it. Punctuation and an
    # instruction elsewhere such as "先别操作" must not turn a question into
    # permission to release a booking.
    changes_requested = bool(changes or reset_quote)
    uncertain_context = changes_requested and bool(
        re.search(
            r"[?？]|只是问|先问|仅讨论|举例|比如|假设|假如|如果|先?(?:别|不要|不用)操作|先不改|暂不|(?:吗|么)[。！!]?\s*$",
            text,
        )
    )
    for change in changes:
        names = (
            [previous.get("required_hotel", "")]
            if change.target == "hotel"
            else previous.get("required_restaurants", [])
        )
        for name in names:
            if name and re.search(
                rf"(?:保留|不换|别换|不要取消|别取消|不取消|不用改|不要改)\s*{re.escape(name)}|{re.escape(name)}\s*(?:不变|照旧|保留|不要换|别换)",
                text,
            ):
                uncertain_context = True
    if reset_quote and re.search(
        r"保留|继续原|原来的行程|不是.*(?:旅行|旅程)|不要重新|别重新", text
    ):
        uncertain_context = True
    if uncertain_context:
        proposed.required_hotel = previous.get("required_hotel", "")
        proposed.required_restaurants = list(previous.get("required_restaurants", []))
        proposed.reservation_notes = previous.get("reservation_notes", "")
        return [
            "这条请求包含询问、暂不操作或保留原安排的意思。已保留指定地点，请明确确认是否取消／替换以及具体目标后再继续。"
        ]
    clauses = [part.strip() for part in re.split(r"[，。；,;!?！？\n]", text) if part.strip()]
    prefix = r"(?:(?:我|我们)(?:决定|想要|想|要)?|请|麻烦)?"
    uncertain = []
    if reset_quote:
        reset = any(
            re.fullmatch(
                prefix
                + r"(?:开始|开启|新建|另开|安排)(?:一趟|一次|一个)?(?:新的旅行|新旅行|新旅程|另一次旅行)",
                clause,
            )
            for clause in clauses
            if reset_quote in text
        )
        if reset:
            return []
        uncertain.append("是否开始另一趟独立旅行尚未明确，原指定地点继续保留。")
    hotel = previous.get("required_hotel", "")
    restaurants = list(
        dict.fromkeys(previous.get("required_restaurants", []) + proposed.required_restaurants)
    )
    notes = previous.get("reservation_notes", "")
    if not hotel:
        hotel = proposed.required_hotel
    suffix = r"(?:的(?:预订|指定|要求|约束|安排|预约))?(?:了|吧)?"
    for change in changes:
        quote = change.user_quote.strip()
        relevant = [
            clause
            for clause in clauses
            if quote and quote in text and (quote in clause or clause in quote)
        ]
        # Never shorten the full clause to the model's potentially negated fragment.
        applied = False
        if change.action == "clear":
            old_names = [hotel] if change.target == "hotel" else restaurants
            if change.name and change.name in old_names:
                name = re.escape(change.name)
                before = (
                    prefix
                    + r"(?:取消|解除|退订|不住|不去|不吃|不要|不用|换掉)(?:原来|之前|原定|已订|必去|的)*"
                    + name
                    + suffix
                )
                after = name + r"(?:这家)?(?:取消|退订|不去了|不住了|不吃了|不用了|换掉)(?:吧)?"
                applied = any(
                    re.fullmatch(before, clause) or re.fullmatch(after, clause)
                    for clause in relevant
                )
                if applied:
                    if change.target == "hotel":
                        hotel = ""
                    else:
                        restaurants = [name for name in restaurants if name != change.name]
            elif not change.name:
                category = (
                    r"(?:酒店|住宿|宾馆|民宿)"
                    if change.target == "hotel"
                    else r"(?:餐厅|饭店|餐饮)"
                )
                all_targets = (
                    prefix + r"(?:取消|解除)(?:所有|全部)(?:指定|已订|必去|的)*" + category + suffix
                )
                applied = any(re.fullmatch(all_targets, clause) for clause in relevant)
                if applied:
                    if change.target == "hotel":
                        hotel = ""
                    else:
                        restaurants = []
        else:
            name = re.escape(change.name)
            specify = (
                prefix
                + (
                    r"(?:酒店|住宿)?(?:换成|改成|改住|必须住|一定住|已订|订好|锁定|就选)"
                    if change.target == "hotel"
                    else r"(?:餐厅|饭店|餐饮)?(?:换成|改成|改去|必须去|必须吃|一定去|一定要去|已订|订好|锁定|就选|必去)"
                )
                + name
                + r"(?:了|吧)?"
            )
            applied = bool(change.name) and any(
                re.fullmatch(specify, clause) for clause in relevant
            )
            if applied:
                if change.target == "hotel":
                    hotel = change.name
                elif change.name not in restaurants:
                    restaurants.append(change.name)
        if not applied:
            uncertain.append(
                "取消或替换的目标与原指令尚未确认，原指定地点继续保留。请明确说明要取消／换成哪一家。"
            )
    retained = (previous.get("required_hotel") and hotel == previous["required_hotel"]) or any(
        name in restaurants for name in previous.get("required_restaurants", [])
    )
    proposed.required_hotel = hotel
    proposed.required_restaurants = restaurants
    if retained and notes and not proposed.reservation_notes:
        proposed.reservation_notes = notes
    return list(dict.fromkeys(uncertain))
