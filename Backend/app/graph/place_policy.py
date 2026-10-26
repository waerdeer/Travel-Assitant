"""Conservative exclusions; absence of a marker never proves a place is open."""

import re

UNAVAILABLE_MARKERS = (
    "建设中",
    "筹建中",
    "装修中",
    "暂停营业",
    "暂不营业",
    "尚未开业",
    "即将开业",
    "已停业",
    "已关闭",
    "永久关闭",
    "停业整顿",
)
STATUS_LABEL = re.compile(r"(?:^|[（(\[【\s:：·_-])(?:停业|歇业|关闭|未开业)(?:$|[）)\]】\s])")
UNAVAILABLE_STATUSES = set(UNAVAILABLE_MARKERS) | {
    "停业",
    "歇业",
    "关闭",
    "未开业",
    "closed",
    "temporarily_closed",
    "permanently_closed",
}
STATUS_FIELDS = ("business_status", "operating_status", "status")


def unavailable_place(data: dict) -> bool:
    name = str(data.get("name", ""))
    return (
        any(
            marker in name
            and (marker != "建设中" or bool(re.search(r"建设中(?![路街巷道])", name)))
            for marker in UNAVAILABLE_MARKERS
        )
        or bool(STATUS_LABEL.search(name))
        or any(
            str(data.get(key, "")).strip().casefold() in UNAVAILABLE_STATUSES
            for key in STATUS_FIELDS
        )
    )


def explicitly_operating(data: dict) -> bool:
    return not unavailable_place(data) and any(
        str(data.get(key, "")).strip().casefold() in {"正常营业", "营业中", "open", "operating"}
        for key in STATUS_FIELDS
    )
