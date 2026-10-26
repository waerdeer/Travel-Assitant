"""Re-check the latest accepted route with real POI detail coordinates.

Read-only regression probe: leaves the original conversation untouched.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.database import async_session_factory, close_db
from app.db.models import AgentCheckpoint
from app.graph.geography import enrich_locations
from app.graph.validation import validate_itinerary
from app.mcp.registry import mcp_client
from app.schemas.planning import Evidence, Itinerary, Requirements


async def main():
    await mcp_client.load_config(str(Path(__file__).resolve().parents[1] / "app/mcp/servers.json"))
    try:
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(AgentCheckpoint).order_by(AgentCheckpoint.updated_at.desc())
                )
            ).scalars()
            snapshot = next(row.state_json for row in rows if row.state_json.get("accepted_plan"))
        state = {**snapshot, "trace": [], "tool_calls": 0}
        update = await enrich_locations(state)
        report = validate_itinerary(
            Itinerary.model_validate(state["itinerary"]),
            Requirements.model_validate(state["requirements"]),
            [Evidence.model_validate(e) for e in update["evidence"]],
        )
        output = {
            "validation": report.model_dump(),
            "trace": update["trace"],
            "selected_places": [
                {"name": e["data"].get("name"), "location": e["data"].get("location")}
                for e in update["evidence"]
                if e["data"].get("location")
            ],
        }
        target = Path(__file__).resolve().parents[2] / "docs/geography-regression.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(json.dumps(report.model_dump(), ensure_ascii=False), flush=True)
    finally:
        await mcp_client.close()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
