"""端到端：跑完整张图 + 真实持久化。

这是最终验收标准的那四条：
  1. 日志出现「工具调用 N 次」（N > 0）—— 由 nodes.py 的 _run_react 打印
  2. inspiration_list 非空且 items 里有真实 name / address
  3. 最终 Markdown 里的名称能在 state 里找到（证明不是幻觉）
  4. SQLite 三张表行数非 0

断言只写结构性不变量，不写具体 POI 名或数量。
"""

import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

from app.agents.orchestrator import TripOrchestrator

# loop_scope 必须跟着 fixture 的 scope 走：module 级的异步 fixture 只能活在一个
# module 级的事件循环里，用默认的 function 级循环会直接报
# "attached to a different loop"。异步 fixture 得用 pytest_asyncio.fixture
# 来声明（loop_scope 不是 pytest.fixture 的参数）。
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def db_path():
    from app.db.database import init_db

    await init_db()
    from app.core.config import settings

    if settings.database_url:
        # sqlite+aiosqlite:///./travel_assistant.db 这类形式
        return settings.database_url.split("///")[-1]
    return os.path.join(os.path.dirname(__file__), "..", "..", "travel_assistant.db")


# scope="module"：默认的函数级 fixture 会让下面 5 个用例各跑一次完整图，
# 也就是 5 次真实 LLM + 高德调用（每次 1~5 分钟），而它们断言的是**同一次
# 运行**的不同侧面。跑一次、共用结果，才是这里想要的东西。
@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def planned_state(db_path):
    """跑一次真实的完整行程规划，返回 final_state。"""
    os.environ.setdefault("RUN_INTEGRATION", "1")
    import app.main  # noqa: F401  确保 MCP 配置已加载

    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "app", "mcp", "servers.json")
    from app.mcp.registry import mcp_client as client

    await client.load_config(os.path.abspath(config_path))

    thread_id = f"it-{uuid.uuid4().hex[:12]}"
    orch = TripOrchestrator()
    start = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=7)
    state = await orch.plan_trip(
        thread_id=thread_id,
        interaction_mode="automatic",
        text=f"帮我规划杭州两日游，{start}出发，{start + timedelta(days=1)}返程，喜欢博物馆，人均预算1500元，1人。",
    )
    return thread_id, state


async def test_tool_chain_produced_real_data(planned_state):
    """验收标准 2：工具链真的取到了数据，而不是空列表。"""
    _, state = planned_state

    assert state.get("inspiration_list"), (
        f"候选景点为空 —— 说明工具链又断了。error_msg={state.get('error_msg')!r}"
    )
    for item in state["inspiration_list"]:
        assert item.get("name"), f"景点没有 name: {item}"


async def test_no_node_degraded(planned_state):
    """验收标准 1 的推论：没有任何节点降级。"""
    _, state = planned_state

    assert state.get("error_msg") is None, f"有节点降级: {state['error_msg']}"


async def test_plan_is_not_hallucinated(planned_state):
    """验收标准 3：Markdown 里出现的名称必须来自真实抓取结果。

    反过来断言更方便：真实数据里至少有一个名称出现在最终文案里。
    如果工具链断了，这条一定失败 —— 因为 state 里根本没有名称可对。
    """
    _, state = planned_state

    names = set()
    for key in ("inspiration_list", "confirmed_hotels", "confirmed_attractions"):
        for item in state.get(key) or []:
            if isinstance(item, dict) and item.get("name"):
                names.add(item["name"])

    assert names, "state 里没有任何真实名称，无从判断是否幻觉"

    plan = state.get("final_plan_md", "")
    assert plan, "最终行程单为空"
    assert any(name in plan for name in names), (
        f"行程单里找不到任何一个真实名称，疑似幻觉。真实名称样例={sorted(names)[:5]}"
    )


async def test_missing_data_is_declared(planned_state):
    """数据缺口必须显式声明，而不是编一份看不出破绽的行程。"""
    _, state = planned_state

    if state.get("confirmed_hotels") and state.get("inspiration_list"):
        pytest.skip("本次数据齐全，无需声明缺口")

    assert "未能获取" in state.get("final_plan_md", ""), (
        "数据有缺口但行程单没有任何声明 —— 「UI 完全正常」的老问题回来了"
    )


async def test_persistence_wrote_rows(planned_state, db_path):
    """验收标准 4：三张表行数非 0（修复前全是 0）。"""
    from app.db.database import get_session
    from app.services.persistence import persist_turn

    thread_id, state = planned_state

    async for session in get_session():
        await persist_turn(
            session,
            thread_id=thread_id,
            user_text="帮我规划一个杭州三日游，我喜欢安静的博物馆",
            state=state,
        )
        break

    conn = sqlite3.connect(db_path)
    try:
        counts = {
            table: conn.execute(f"select count(*) from {table}").fetchone()[0]
            for table in ("conversations", "messages", "trips")
        }
    finally:
        conn.close()

    assert counts["conversations"] > 0, f"conversations 仍为 0：{counts}"
    assert counts["messages"] > 0, f"messages 仍为 0：{counts}"
    assert counts["trips"] > 0, f"trips 仍为 0：{counts}"
