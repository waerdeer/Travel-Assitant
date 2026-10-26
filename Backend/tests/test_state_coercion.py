"""
状态类型收敛测试 —— 纯函数 + pydantic，零网络。

背景（持久化 P0）：
    custom_preferences 在 TripState 声明是 str、DB 列是 Text，但 router_node
    的裸 JSON fallback 路径没有任何类型校验，LLM 吐个 {} 就一路带进 DB：

        sqlite3.InterfaceError: Error binding parameter 5
        [parameters: ('e2e-demo', '上海', ..., '通用标准', {}, 'completed', ...)]

    persist_turn 是单事务的，整轮回滚 —— conversations / messages / trips
    三张表因此至今 0 行。

根因不是「LLM 不听话」，是 RouterOutput 有两条产出路径
（with_structured_output 一条、裸 JSON 一条）而只有第一条经过 pydantic 校验。
"""

import pytest
from pydantic import ValidationError

from app.core.coerce import as_text
from app.graph.nodes import RouterOutput


# ---------- as_text ----------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("上海", "上海"),
        ("", ""),
        (None, ""),
        ("通用标准", "通用标准"),
        (123, "123"),
        (0, "0"),
        (True, "True"),
    ],
)
def test_as_text_scalars(value, expected):
    assert as_text(value) == expected


def test_as_text_serializes_dict():
    """这正是炸掉整轮写入的那个 {}。"""
    assert as_text({}) == "{}"
    assert as_text({"安静": True}) == '{"安静": true}'
    # 中文必须保持可读，不能变成 \uXXXX
    assert "安静" in as_text({"quiet": "安静"})


def test_as_text_serializes_list():
    assert as_text([]) == "[]"
    assert as_text(["亲子", "安静"]) == '["亲子", "安静"]'


@pytest.mark.parametrize("value", [{"a": {1, 2}}, object(), {1, 2}])
def test_as_text_never_raises(value):
    """契约是「永不抛出」——它的调用点正是那个不该回滚事务的地方。"""
    assert isinstance(as_text(value), str)


# ---------- RouterOutput 校验器 ----------


def test_router_output_coerces_dict_preference():
    """核心回归：这个 dict 曾经一路带到 SQLAlchemy 的 Text 列上。"""
    out = RouterOutput(
        intent="new_trip", city="上海市", custom_preferences={"安静": True, "亲子": True}
    )
    assert isinstance(out.custom_preferences, str)
    assert "安静" in out.custom_preferences


def test_router_output_coerces_all_text_fields():
    out = RouterOutput.model_validate(
        {
            "intent": "new_trip",
            "city": {"name": "上海市"},  # LLM 偶尔会套一层
            "start_date": None,
            "end_date": ["2026-08-19"],
            "custom_preferences": ["亲子", "安静"],
        }
    )
    for field in ("city", "start_date", "end_date", "custom_preferences"):
        assert isinstance(getattr(out, field), str), f"{field} 应为 str"


def test_router_output_fallback_path_is_validated():
    """两条产出路径必须收敛成同一条契约。

    旧实现的 fallback 用 parsed.get(...) 手工取值，field_validator 完全不生效。
    改成 model_validate 之后，同样的脏数据会被同一条校验规则接住。
    """
    dirty_json = '{"intent": "new_trip", "city": "杭州市", "custom_preferences": {}}'
    import json

    out = RouterOutput.model_validate(json.loads(dirty_json))
    assert out.custom_preferences == "{}"
    assert isinstance(out.custom_preferences, str)


def test_router_output_defaults_are_strings():
    out = RouterOutput(intent="chat")
    assert out.city == ""
    assert out.custom_preferences == ""


def test_router_output_still_rejects_missing_intent():
    """收敛类型不等于放弃校验：intent 是必填的。"""
    with pytest.raises(ValidationError):
        RouterOutput.model_validate({"city": "上海市"})


# ---------- persist_turn 的兜底收口 ----------


async def test_persist_turn_survives_dirty_state():
    """第三层收口的回归测试：脏 state 不许让整轮写入回滚。

    这里用一个记录调用的假 session/crud，断言 persist_turn 拿到的是字符串，
    且最终执行到了 commit —— 旧实现在 commit 前就抛 InterfaceError 了。
    """
    from app.services import persistence

    recorded = {}

    class FakeSession:
        def add(self, obj):
            recorded.setdefault("added", []).append(obj)

        async def commit(self):
            recorded["committed"] = True

        async def rollback(self):
            recorded["rolled_back"] = True

    async def fake_upsert_conversation(session, **kwargs):
        recorded["conversation"] = kwargs

    async def fake_upsert_trip(session, **kwargs):
        recorded["trip"] = kwargs

    def fake_new_message(thread_id, role, content, intent):
        recorded.setdefault("messages", []).append((role, content))
        return object()

    monkeypatch_kwargs = {
        "upsert_conversation": fake_upsert_conversation,
        "upsert_trip": fake_upsert_trip,
        "new_message": fake_new_message,
    }
    original = {k: getattr(persistence.crud, k) for k in monkeypatch_kwargs}
    for k, v in monkeypatch_kwargs.items():
        setattr(persistence.crud, k, v)
    try:
        await persistence.persist_turn(
            FakeSession(),
            thread_id="t-dirty",
            user_text="帮我规划上海三日游",
            state={
                "intent": "new_trip",
                "city": {"name": "上海市"},  # 脏
                "start_date": None,  # 脏
                "custom_preferences": {},  # 脏 —— 就是它炸掉过整轮写入
                "final_plan_md": "## 行程",
                "messages": [],
            },
        )
    finally:
        for k, v in original.items():
            setattr(persistence.crud, k, v)

    assert recorded.get("committed") is True, "必须走到 commit"
    assert "rolled_back" not in recorded, "脏类型不该导致回滚"

    # 落到 crud 的必须全是字符串
    conv = recorded["conversation"]
    for field in ("city", "start_date", "end_date", "persona", "custom_preferences"):
        assert isinstance(conv[field], str), f"{field} 传给 crud 时仍是 {type(conv[field])}"
    assert conv["custom_preferences"] == "{}"


# ---------- 真实 SQLite 的端到端写入 ----------


async def test_persist_turn_against_real_sqlite(tmp_path):
    """用真实 SQLAlchemy + SQLite 复现原始故障场景。

    上面那个用假 session 的测试只能证明「传给 crud 的是字符串」，
    证明不了绑定层真的不炸 —— 而原始报错恰恰发生在绑定层：

        sqlite3.InterfaceError: Error binding parameter 5 - probably unsupported type.

    这里建一个临时库、真实建表、真实 commit，喂进当初炸掉整轮写入的那个 state。
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.base import Base
    from app.db import models  # noqa: F401  确保模型注册到 metadata
    from app.services.persistence import persist_turn

    db_file = tmp_path / "coercion.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await persist_turn(
                session,
                thread_id="t-real",
                user_text="帮我规划上海三日游",
                state={
                    "intent": "new_trip",
                    # 下面这几个字段就是当初 parameters 里出现的脏值
                    "city": "上海市",
                    "start_date": "2026-08-18",
                    "end_date": "2026-08-20",
                    "persona": "通用标准",
                    "custom_preferences": {},  # ← Error binding parameter 5
                    "inspiration_list": [{"name": "外滩", "address": "黄浦区"}],
                    "confirmed_hotels": [],
                    "final_plan_md": "## 上海三日游",
                    "messages": [],
                },
            )

        # 三张表都必须有行 —— 修复前它们全是 0
        async with factory() as session:
            for table in ("conversations", "messages", "trips"):
                count = (
                    await session.execute(text(f"select count(*) from {table}"))
                ).scalar()
                assert count > 0, f"{table} 行数为 0 —— 整轮写入又被回滚了"

            stored = (
                await session.execute(
                    text(
                        "select custom_preferences from conversations "
                        "where thread_id = 't-real'"
                    )
                )
            ).scalar()
        assert stored == "{}", f"落库的不是收敛后的字符串: {stored!r}"
    finally:
        await engine.dispose()
