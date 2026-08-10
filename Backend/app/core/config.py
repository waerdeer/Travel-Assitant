"""
=====================================================================
模块名称: config.py
功能描述: 全局配置文件，加载环境变量并管理基础配置信息。
=====================================================================
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    amap_maps_api_key: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
