"""Real model + MCP smoke check; saves a redacted, reproducible run report.

Run from Backend: ../.venv/bin/python scripts/smoke_agent.py
Use DATABASE_URL=sqlite+aiosqlite:////tmp/... to isolate demonstration data.
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
    thread = "smoke-" + uuid.uuid4().hex[:12]
    start = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=7)
    prompts = [
        "帮我规划杭州两天游，喜欢博物馆和湖边散步，人均预算1000元。",
        f"出发日期是{start.isoformat()}，返程是{(start + timedelta(days=1)).isoformat()}，1个人。",
        "行程改成轻松一点，每天最多两个景点，其他要求保持不变。",
        "住宿换成原来游玩区域附近的经济型酒店，其他每日行程不要改。",
    ]
    records = []
    try:
        for prompt in prompts:
            result = await TripOrchestrator().plan_trip(
                thread, prompt, interaction_mode="automatic"
            )
            record = {
                "prompt": prompt,
                "status": result.get("status"),
                "requirements": result.get("requirements"),
                "validation": result.get("validation"),
                "metrics": result.get("metrics"),
                "trace": result.get("trace"),
                "error_msg": result.get("error_msg"),
                "persisted": result.get("persisted"),
                "evidence_count": len(result.get("evidence", [])),
                "plan_md": result.get("final_plan_md", ""),
                "itinerary": result.get("itinerary"),
            }
            records.append(record)
            print(
                json.dumps(
                    {
                        k: record[k]
                        for k in (
                            "status",
                            "metrics",
                            "evidence_count",
                            "error_msg",
                            "persisted",
                        )
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        report_path = Path(__file__).resolve().parents[2] / "docs/live-smoke-report.json"
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "run_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                    "requested_model": settings.llm_model,
                    "limits": {
                        "max_tool_calls": settings.max_tool_calls,
                        "max_plan_repairs": settings.max_plan_repairs,
                    },
                    "turns": records,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        assert records[0]["status"] == "awaiting_clarification"
        assert records[1]["status"] in ("completed", "degraded")
        assert records[2]["status"] in ("completed", "degraded")
        assert records[3]["status"] in ("completed", "degraded")
        assert records[3]["itinerary"]["days"] == records[2]["itinerary"]["days"]
        print("Live smoke checks passed", flush=True)
    finally:
        await mcp_client.close()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
