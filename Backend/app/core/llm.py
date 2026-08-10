from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.core.exceptions import TripPlannerError


@dataclass
class ToolCall:
    """LLM 返回的工具调用。"""
    name: str
    arguments: dict


@dataclass
class LLMResult:
    """LLM 响应结果。"""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient:
    """LLM 调用封装，支持纯文本和 function calling 两种模式。"""

    async def chat(self, prompt: str, tools: list[dict] = None) -> LLMResult:
        if not settings.llm_api_key:
            raise TripPlannerError("未配置 LLM_API_KEY")

        messages = [{"role": "user", "content": prompt}]
        payload = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": 0.7,
        }

        if tools:
            payload["tools"] = tools

        data = await self._request(payload)
        return self._parse_response(data)

    async def _request(self, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{settings.llm_base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    def _parse_response(self, data: dict) -> LLMResult:
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise TripPlannerError(f"LLM 响应格式异常: {data}") from e

        content = message.get("content", "") or ""
        raw_calls = message.get("tool_calls") or []

        tool_calls = [
            ToolCall(
                name=call["function"]["name"],
                arguments=eval(call["function"]["arguments"]),
            )
            for call in raw_calls
        ]

        return LLMResult(content=content, tool_calls=tool_calls)


llm_client = LLMClient()
