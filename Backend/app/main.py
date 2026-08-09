import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.mcp.registry import mcp_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_path = os.path.join(os.path.dirname(__file__), "mcp", "servers.json")
    await mcp_client.load_config(config_path)
    yield
    await mcp_client.close()


app = FastAPI(
    title="旅行助手 API",
    description="Multi-Agent 旅行规划服务，支持 MCP 工具调用与多领域 Skill",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#挂载注册router，并在地址上都添加前缀 /api/v1
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
