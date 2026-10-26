"""
=====================================================================
模块名称: config.py
功能描述: 全局配置文件，加载环境变量并管理基础配置信息。
=====================================================================
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from pydantic import Field


class Settings(BaseSettings):
    amap_maps_api_key: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    # 数据库连接串，留空时默认使用 Backend/travel_assistant.db
    database_url: str = ""
    llm_timeout_seconds: float = Field(default=90, ge=5, le=180)
    agent_timeout_seconds: float = Field(default=300, ge=10, le=600)
    max_plan_repairs: int = Field(default=2, ge=0, le=3)
    max_tool_calls: int = Field(default=24, ge=1, le=40)
    mcp_min_interval_seconds: float = Field(default=1.05, ge=0, le=5)

    # 启动时若 MCP 工具名校验不通过，是否直接让服务起不来。
    # 默认 False：个人项目经常离线改代码/跑测试，校验一旦会挡住 uvicorn，
    # 第一反应就是把校验删掉，那这个校验就白做了。默认只记 CRITICAL 日志
    # 并在 /health 上暴露 mcp_health=false。
    mcp_strict_startup: bool = False

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
