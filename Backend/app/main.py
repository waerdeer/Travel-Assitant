import os
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            os.path.join(LOG_DIR, "app.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
        ),
    ],
)
# HTTP request logs include the MCP key in its query string. Keep library logs
# at WARNING and redact configured secrets on every application log handler.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from app.api.browse import router as browse_router
from app.api.place_images import router as place_images_router
from app.api.routes import router as api_router
from app.api.history import router as history_router
from app.core.config import settings
from app.graph.tools import AMAP_REQUIRED_TOOLS, AMAP_SERVER
from app.mcp.registry import mcp_client
from app.db.database import init_db, close_db

logger = logging.getLogger("app.main")


class SecretFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        for secret in (settings.llm_api_key, settings.amap_maps_api_key):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        record.msg, record.args = message, ()
        return True


for handler in logging.getLogger().handlers:
    handler.addFilter(SecretFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    config_path = os.path.join(os.path.dirname(__file__), "mcp", "servers.json")
    await mcp_client.load_config(config_path)
    logger.info("MCP 配置加载完成")

    # 启动即校验工具名。
    # 本次事故里工具名错了两层（代码 + 文档）却一直没被发现，就是因为
    # 没有任何地方在启动时问过服务端「你到底有哪些工具」。校验结果挂到
    # app.state 上，由 /health 暴露出去。
    mcp_health = await mcp_client.validate_tools(AMAP_SERVER, AMAP_REQUIRED_TOOLS)
    app.state.mcp_health = mcp_health
    if not mcp_health["ok"] and settings.mcp_strict_startup:
        raise RuntimeError(
            f"MCP 工具校验失败（mcp_strict_startup=True）：{mcp_health}"
        )

    yield
    await close_db()
    await mcp_client.close()


app = FastAPI(
    title="旅行助手 API",
    description="旅行规划 Agent：需求澄清、MCP 证据检索、结构化规划、确定性校验和有限修正",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
app.include_router(browse_router, prefix="/api/v1")
app.include_router(place_images_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")


@app.get("/health")
async def health(request: Request):
    """健康检查。mcp_health 让「工具链断了」这件事在 UI 之外也能被看见。

    旧版永远返回 {"status": "ok"} —— 而当时四个工具全在返回空数据、
    三张表全是 0 行。这个端点在那段时间里持续报告「一切正常」，
    是「UI 完全正常、不报错」这个最恶劣特性的一个缩影。

    status 的取值刻意分成三档：
      ok       —— 工具清单校验通过
      degraded —— 服务端连不上（离线开发常见），或工具名不匹配
    连不上时对 required 工具而言仍然是不可用，所以也算 degraded。
    """
    mcp_health = getattr(request.app.state, "mcp_health", None)
    degraded = bool(mcp_health) and not mcp_health.get("ok", True)
    return {
        "status": "degraded" if degraded else "ok",
        "mcp_health": mcp_health,
    }
