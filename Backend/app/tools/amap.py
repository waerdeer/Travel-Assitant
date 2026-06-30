import re
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import ToolCallError


@dataclass
class ToolCall:
    tool_name: str
    params: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str) -> "ToolCall":
        pattern = r"\[TOOL_CALL:(\w+):(.+?)\]"
        match = re.search(pattern, text)
        if not match:
            raise ToolCallError(f"未找到工具调用: {text}")

        tool_name = match.group(1)
        raw_params = match.group(2)
        params = {}
        for pair in raw_params.split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                params[key.strip()] = value.strip()

        return cls(tool_name=tool_name, params=params)


class AmapClient:
    base_url = "https://restapi.amap.com/v3"

    @classmethod
    async def text_search(cls, keywords: str, city: str = "", **kwargs: Any) -> list[dict]:
        raise NotImplementedError("需接入高德地图 API")

    @classmethod
    async def weather_query(cls, city: str, **kwargs: Any) -> list[dict]:
        raise NotImplementedError("需接入高德天气 API")
