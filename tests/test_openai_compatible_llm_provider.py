from functools import partial
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import OpenAI

from notebook_intelligence.api import CancelToken, CompletionContext

from notebook_intelligence.base_chat_participant import (
    _chat_history_context_window,
)
from notebook_intelligence.llm_providers.openai_compatible_llm_provider import (
    DEFAULT_CONTEXT_WINDOW,
    OpenAICompatibleLLMProvider,
    sanitize_tools_for_openai_compatible,
)


def test_sanitize_tools_for_openai_compatible_removes_function_strict_without_mutating_input():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "python",
                "description": "Run python",
                "strict": True,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }
    ]

    sanitized = sanitize_tools_for_openai_compatible(tools)

    assert sanitized[0]["function"].get("strict") is None
    assert tools[0]["function"]["strict"] is True


def test_blank_context_window_does_not_trigger_history_pruning():
    model = OpenAICompatibleLLMProvider().chat_models[0]

    assert model.context_window == DEFAULT_CONTEXT_WINDOW
    assert model.context_window_is_configured is False
    assert _chat_history_context_window(model) == 0

    model.set_property_value("context_window", "65536")

    assert model.context_window_is_configured is True
    assert _chat_history_context_window(model) == 65536


@patch("openai.OpenAI")
def test_openai_compatible_chat_model_drops_strict_before_request(mock_openai_cls):
    provider = OpenAICompatibleLLMProvider()
    model = provider.chat_models[0]
    model.set_property_value("model_id", "test-model")
    model.set_property_value("api_key", "test-key")
    model.set_property_value("base_url", "https://example.com/v1")

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.model_dump_json.return_value = '{"choices": [{"message": {"content": "ok"}}]}'
    mock_response.choices = [MagicMock(message=MagicMock(reasoning_content=None, reasoning=None))]
    mock_client.chat.completions.create.return_value = mock_response

    tools = [
        {
            "type": "function",
            "function": {
                "name": "python",
                "description": "Run python",
                "strict": True,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }
    ]

    result = model.completions(messages=[{"role": "user", "content": "hi"}], tools=tools)

    assert result["choices"][0]["message"]["content"] == "ok"
    create_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert "strict" not in create_kwargs["tools"][0]["function"]
    assert tools[0]["function"]["strict"] is True


@pytest.mark.parametrize("mode", ["chat", "inline"])
@pytest.mark.parametrize("set_key, configured_key", [
    pytest.param(False, None, id="unset"),
    pytest.param(True, None, id="null"),
    pytest.param(True, "", id="empty"),
    pytest.param(True, " \t ", id="whitespace"),
    pytest.param(True, "configured-key", id="explicit"),
])
def test_api_key_fallback_reaches_request(monkeypatch, mode, set_key, configured_key):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    provider = OpenAICompatibleLLMProvider()
    model = provider.chat_models[0] if mode == "chat" else provider.inline_completion_models[0]
    model.set_property_value("model_id", "test-model")
    model.set_property_value("base_url", "https://example.com/v1")
    if set_key:
        model.set_property_value("api_key", configured_key)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "test-completion",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        with patch("openai.OpenAI", wraps=partial(OpenAI, http_client=http_client)):
            if mode == "chat":
                result = model.completions(messages=[{"role": "user", "content": "hi"}])
                assert result["choices"][0]["message"]["content"] == "ok"
            else:
                assert model.inline_completions("", "", "python", "test.py", CompletionContext([]), CancelToken()) == "ok"

    expected_key = "configured-key" if configured_key == "configured-key" else "environment-key"
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == f"Bearer {expected_key}"
