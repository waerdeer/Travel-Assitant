"""Stable identity for the accepted plan and its browsing context."""

import hashlib
import json


def plan_version(data: dict) -> str:
    body = {key: data.get(key) for key in ("itinerary", "requirements", "evidence")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
