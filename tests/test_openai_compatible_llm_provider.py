import re
from contextlib import nullcontext
from functools import partial
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import OpenAI, OpenAIError

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


@pytest.mark.parametrize("environment_key", [None, "", "environment-key"], ids=["env-unset", "env-empty", "env-set"])
@pytest.mark.parametrize("mode", ["chat", "inline"])
@pytest.mark.parametrize("set_key, configured_key", [
    pytest.param(False, None, id="unset"),
    pytest.param(True, None, id="null"),
    pytest.param(True, "", id="empty"),
    pytest.param(True, " \t ", id="whitespace"),
    pytest.param(True, "configured-key", id="explicit"),
])
def test_api_key_fallback_reaches_request(monkeypatch, mode, set_key, configured_key, environment_key):
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    if environment_key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", environment_key)
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

    expected_error = nullcontext()
    missing_key = False
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        # Compare keyless requests with the installed SDK's handling of the
        # original saved value. Some versions reject even an empty string.
        if not environment_key and not (configured_key or "").strip():
            saved_key = None if set_key and configured_key is None else ""
            try:
                OpenAI(api_key=saved_key, http_client=http_client)
            except OpenAIError as error:
                expected_error = pytest.raises(type(error), match=re.escape(str(error)))
                missing_key = True
        with expected_error, patch("openai.OpenAI", wraps=partial(OpenAI, http_client=http_client)) as client_class:
            if mode == "chat":
                result = model.completions(messages=[{"role": "user", "content": "hi"}])
                assert result["choices"][0]["message"]["content"] == "ok"
            else:
                assert model.inline_completions("", "", "python", "test.py", CompletionContext([]), CancelToken()) == "ok"

    if configured_key and configured_key.strip():
        expected_key = configured_key
    elif environment_key or (set_key and configured_key is None):
        expected_key = None
    else:
        expected_key = ""
    client_class.assert_called_once_with(base_url="https://example.com/v1", api_key=expected_key)

    if missing_key:
        assert requests == []
        return
    assert len(requests) == 1
    assert str(requests[0].url) == "https://example.com/v1/chat/completions"
    if configured_key == "configured-key":
        assert requests[0].headers["Authorization"] == "Bearer configured-key"
    elif environment_key:
        assert requests[0].headers["Authorization"] == "Bearer environment-key"
    else:
        assert "Authorization" not in requests[0].headers


def test_api_key_is_optional_for_chat_and_inline_settings():
    provider = OpenAICompatibleLLMProvider()
    for model in [*provider.chat_models, *provider.inline_completion_models]:
        assert model.get_property("api_key").to_dict()["optional"] is True
        assert model.get_property("model_id").to_dict()["optional"] is False
