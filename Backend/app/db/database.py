"""
=====================================================================
模块名称: database.py
功能描述: 异步数据库引擎与会话管理
         - 默认 SQLite 文件：Backend/travel_assistant.db（绝对路径，避免 CWD 依赖）
         - 每次连接启用 WAL / 外键 / busy_timeout
=====================================================================
"""

import logging
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base

logger = logging.getLogger("app.db")


def _default_sqlite_url() -> str:
    """计算 Backend/ 目录下的默认 SQLite 数据库绝对路径"""
    backend_dir = Path(__file__).resolve().parents[2]  # Backend/
    db_path = backend_dir / "travel_assistant.db"
    return f"sqlite+aiosqlite:///{db_path}"


DATABASE_URL = settings.database_url or _default_sqlite_url()

engine = create_async_engine(DATABASE_URL, echo=False)

async_session_factory: sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


# SQLite 连接级 PRAGMA：
#  - journal_mode=WAL    提升并发读写能力
#  - foreign_keys=ON     让 ON DELETE CASCADE 真正在数据库层生效
#  - busy_timeout=5000   缓解并发写导致的 "database is locked"
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async def get_session() -> AsyncSession:
    """FastAPI 依赖：提供一个会话，请求结束后自动关闭"""
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """启动时建表（幂等）。首个版本用 create_all，后续需要迁移时再引入 Alembic。"""
    # 导入模型以确保注册到 Base.metadata
    from app.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据库初始化完成: %s", DATABASE_URL)


async def close_db() -> None:
    """关闭数据库连接池"""
    await engine.dispose()
