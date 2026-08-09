"""
=====================================================================
模块名称: llm.py
功能描述: 大语言模型（LLM）客户端封装，负责处理和模型 API 的交互。
=====================================================================
"""

import httpx
from app.core.config import settings
from app.core.exceptions import TripPlannerError


class LLMClient:
    """统一 LLM 调用封装（OpenAI 兼容协议）。"""

    async def chat(self, prompt: str, system: str = "") -> str:
        if not settings.llm_api_key:
            raise TripPlannerError("未配置 LLM_API_KEY")

        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": 0.7,
        }

        url = f"{settings.llm_base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise TripPlannerError(f"LLM 响应格式异常: {data}") from e


llm_client = LLMClient()

__all__ = [
    "LLMClient",
    "llm_client",
]