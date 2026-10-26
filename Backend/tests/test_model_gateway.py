import httpx
import pytest
from langchain_core.messages import AIMessage
from openai import APIConnectionError, AuthenticationError
from pydantic import BaseModel

from app.services import model_gateway


class Answer(BaseModel):
    reply: str


@pytest.mark.parametrize(
    "error,expected_calls,success",
    [
        (APIConnectionError(request=httpx.Request("POST", "https://example.test")), 2, True),
        (
            AuthenticationError(
                "invalid key",
                response=httpx.Response(401, request=httpx.Request("POST", "https://example.test")),
                body=None,
            ),
            1,
            False,
        ),
    ],
)
async def test_transient_failure_retries_once_but_invalid_auth_never_retries(
    monkeypatch, error, expected_calls, success
):
    calls = []

    class Model:
        def bind(self, **kwargs):
            return self

        async def ainvoke(self, messages):
            calls.append(messages)
            if len(calls) == 1:
                raise error
            return AIMessage(
                content='{"reply":"ok"}',
                usage_metadata={"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
            )

    monkeypatch.setattr(model_gateway, "get_model", lambda: Model())
    if success:
        answer, usage = await model_gateway.ask_json(Answer, "Reply as JSON", {})
        assert answer.reply == "ok"
        assert usage["model_calls"] == 2
        assert usage["output_tokens"] == 4
    else:
        with pytest.raises(model_gateway.ModelCallError) as caught:
            await model_gateway.ask_json(Answer, "Reply as JSON", {})
        assert caught.value.code == "AuthenticationError"
        assert caught.value.usage["model_calls"] == 1
    assert len(calls) == expected_calls


async def test_persistent_connection_failure_stops_after_two_calls(monkeypatch):
    calls = []

    class Model:
        def bind(self, **kwargs):
            return self

        async def ainvoke(self, messages):
            calls.append(messages)
            raise APIConnectionError(request=httpx.Request("POST", "https://example.test"))

    monkeypatch.setattr(model_gateway, "get_model", lambda: Model())
    with pytest.raises(model_gateway.ModelCallError) as caught:
        await model_gateway.ask_json(Answer, "Reply as JSON", {})
    assert len(calls) == caught.value.usage["model_calls"] == 2
