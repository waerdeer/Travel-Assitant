"""Real single-day planning + follow-up regression, against an isolated DB.

From Backend:
DATABASE_URL=sqlite+aiosqlite:////tmp/travel-single-day.db \
    ../.venv/bin/python scripts/smoke_single_day.py
"""

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.orchestrator import TripOrchestrator
from app.core.config import settings
from app.db.database import close_db, init_db
from app.mcp.registry import mcp_client


async def main():
    await init_db()
    await mcp_client.load_config(str(Path(__file__).resolve().parents[1] / "app/mcp/servers.json"))
    thread = "one-day-" + uuid.uuid4().hex[:12]
    start = (datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=14)).isoformat()
    prompts = [
        f"{start}去苏州一日游，1个人，人均预算500元，喜欢园林，"
        "每天最多两个景点，吃苏帮菜，不住酒店。",
        "这个计划是不是不用再查营业时间和价格就可以直接出发了？请简短说明。",
    ]
    records = []
    try:
        for prompt in prompts:
            result = await TripOrchestrator().plan_trip(
                thread, prompt, interaction_mode="automatic"
            )
            record = {
                key: result.get(key)
                for key in (
                    "status",
                    "reply",
                    "requirements",
                    "validation",
                    "metrics",
                    "trace",
                    "error_msg",
                    "persisted",
                    "itinerary",
                    "final_plan_md",
                )
            }
            record["prompt"] = prompt
            records.append(record)
            print(
                json.dumps({k: record[k] for k in ("status", "metrics", "persisted")}), flush=True
            )
        output = Path(__file__).resolve().parents[2] / "docs/live-single-day-report.json"
        output.write_text(
            json.dumps(
                {
                    "run_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                    "requested_model": settings.llm_model,
                    "turns": records,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        first, chat = records
        assert first["status"] in ("completed", "degraded"), first["reply"]
        assert first["validation"]["passed"]
        assert len(first["itinerary"]["days"]) == 1
        assert not first["itinerary"]["hotel_evidence_id"]
        assert first["itinerary"]["costs"]["accommodation"] == 0
        assert (
            sum(
                first["itinerary"]["costs"][key]
                for key in ("accommodation", "meals", "transport", "tickets")
            )
            <= 500
        )
        assert all(event.get("tool") != "search_hotels" for event in first["trace"])
        assert first["metrics"]["tool_calls"] <= settings.max_tool_calls
        assert chat["status"] == "chat"
        assert chat["metrics"]["tool_calls"] == 0
        assert chat["validation"] == {}
        assert all(t["persisted"] for t in records)
        print("Single-day smoke passed; review the saved reply for semantic accuracy.", flush=True)
    finally:
        await mcp_client.close()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
