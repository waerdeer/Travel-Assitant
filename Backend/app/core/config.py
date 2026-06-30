from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    amap_api_key: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
