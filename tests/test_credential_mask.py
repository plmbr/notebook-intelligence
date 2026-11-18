# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""A stored API key reaches the browser masked and survives a round trip."""

import json

from notebook_intelligence.api import LLMProviderProperty
from notebook_intelligence.credential_mask import (
    SECRET_MASK,
    mask_model_config,
    mask_model_properties,
    mask_secret,
    mask_settings_api_key,
    restore_masked_api_key,
    restore_masked_model_properties,
)
from notebook_intelligence.llm_providers.litellm_compatible_llm_provider import (
    LiteLLMCompatibleLLMProvider,
)
from notebook_intelligence.llm_providers.openai_compatible_llm_provider import (
    OpenAICompatibleLLMProvider,
)


def _model(provider="openai-compatible", model="m", key="sk-real"):
    return {
        "provider": provider,
        "id": model,
        "properties": [
            {"id": "api_key", "value": key, "secret": True},
            {"id": "base_url", "value": "https://x", "secret": False},
        ],
    }


class TestMasking:
    def test_mask_secret_keeps_empty_values_empty(self):
        assert mask_secret("") == ""
        assert mask_secret(None) is None
        assert mask_secret("sk-real") == SECRET_MASK

    def test_settings_key_masked_on_a_copy(self):
        settings = {"api_key": "sk-real", "enabled": True}
        assert mask_settings_api_key(settings) == {
            "api_key": SECRET_MASK,
            "enabled": True,
        }
        assert settings["api_key"] == "sk-real"

    def test_only_secret_properties_are_masked(self):
        original = _model()
        masked = mask_model_properties([original])[0]
        values = {p["id"]: p["value"] for p in masked["properties"]}
        assert values == {"api_key": SECRET_MASK, "base_url": "https://x"}
        assert original["properties"][0]["value"] == "sk-real"

    def test_unflagged_api_key_property_is_masked_and_flagged(self):
        model = {
            "provider": "ext",
            "id": "m",
            "properties": [
                {"id": "api_key", "value": "sk-real"},
                {"id": "base_url", "value": "https://x"},
            ],
        }
        masked = mask_model_properties([model])[0]["properties"]
        assert masked[0] == {"id": "api_key", "value": SECRET_MASK, "secret": True}
        assert masked[1] == {"id": "base_url", "value": "https://x"}

    def test_blank_secret_property_stays_blank(self):
        masked = mask_model_properties([_model(key="")])[0]
        assert masked["properties"][0]["value"] == ""

    def test_built_in_api_key_properties_are_flagged_secret(self):
        for provider in (OpenAICompatibleLLMProvider(), LiteLLMCompatibleLLMProvider()):
            for model in provider.chat_models + provider.inline_completion_models:
                assert model.get_property("api_key").secret is True
                assert model.get_property("model_id").secret is False

    def test_property_to_dict_carries_the_flag(self):
        assert LLMProviderProperty("k", "K", "K", "v", secret=True).to_dict()[
            "secret"
        ] is True


class TestMaskModelConfig:
    def test_masks_secret_properties_of_a_stored_entry(self):
        stored = {
            "provider": "litellm-compatible",
            "model": "m",
            "properties": [
                {"id": "api_key", "value": "sk-real"},
                {"id": "base_url", "value": "https://x"},
            ],
        }
        assert mask_model_config(stored) == {
            "provider": "litellm-compatible",
            "model": "m",
            "properties": [
                {"id": "api_key", "value": SECRET_MASK},
                {"id": "base_url", "value": "https://x"},
            ],
        }
        assert stored["properties"][0]["value"] == "sk-real"

    def test_entries_without_properties_pass_through(self):
        copilot = {"provider": "github-copilot", "model": "gpt-4.1"}
        assert mask_model_config(copilot) is copilot
        assert mask_model_config(None) is None

    def test_a_real_nbi_config_entry_is_masked(self, tmp_path):
        from notebook_intelligence.config import NBIConfig

        config = NBIConfig.__new__(NBIConfig)
        config._feature_policies, config._string_overrides = {}, {}
        config.env_config = {}
        config.user_config = {
            "chat_model": {
                "provider": "openai-compatible",
                "model": "openai-compatible-chat-model",
                "properties": [{"id": "api_key", "value": "sk-LEAK"}],
            }
        }
        assert "sk-LEAK" in json.dumps(config.chat_model)
        assert "sk-LEAK" not in json.dumps(mask_model_config(config.chat_model))


class TestRestore:
    def test_posted_mask_becomes_the_stored_key(self):
        assert restore_masked_api_key(
            {"api_key": SECRET_MASK, "enabled": False}, {"api_key": "sk-real"}
        ) == {"api_key": "sk-real", "enabled": False}

    def test_new_key_is_kept(self):
        assert restore_masked_api_key(
            {"api_key": "sk-new"}, {"api_key": "sk-real"}
        ) == {"api_key": "sk-new"}

    def test_cleared_key_stays_cleared(self):
        assert restore_masked_api_key(
            {"api_key": ""}, {"api_key": "sk-real"}
        ) == {"api_key": ""}

    def test_mask_with_nothing_stored_is_never_saved(self):
        assert restore_masked_api_key({"api_key": SECRET_MASK}, None) == {
            "api_key": ""
        }

    def test_model_mask_restored_for_the_same_model(self):
        stored = {
            "provider": "openai-compatible",
            "model": "m",
            "properties": [{"id": "api_key", "value": "sk-real"}],
        }
        posted = {
            "provider": "openai-compatible",
            "model": "m",
            "properties": [
                {"id": "api_key", "value": SECRET_MASK},
                {"id": "base_url", "value": "https://y"},
            ],
        }
        restored = restore_masked_model_properties(posted, stored)
        assert restored["properties"] == [
            {"id": "api_key", "value": "sk-real"},
            {"id": "base_url", "value": "https://y"},
        ]

    def test_model_mask_for_another_model_is_dropped(self):
        stored = {
            "provider": "openai-compatible",
            "model": "m",
            "properties": [{"id": "api_key", "value": "sk-real"}],
        }
        posted = {
            "provider": "litellm-compatible",
            "model": "other",
            "properties": [{"id": "api_key", "value": SECRET_MASK}],
        }
        restored = restore_masked_model_properties(posted, stored)
        assert restored["properties"] == [{"id": "api_key", "value": ""}]

    def test_model_without_properties_passes_through(self):
        posted = {"provider": "github-copilot", "model": "gpt-4.1"}
        assert restore_masked_model_properties(posted, None) is posted


class TestCapabilitiesResponse:
    """GetCapabilitiesHandler.get is where the masks are applied."""

    def test_no_stored_key_reaches_the_response(self, monkeypatch):
        from unittest.mock import MagicMock

        from notebook_intelligence import extension as ext_module

        manager = MagicMock()
        manager.chat_model_ids = [_model(key="sk-chat")]
        manager.inline_completion_model_ids = [_model(key="sk-inline")]
        manager.nbi_config.claude_settings = {"api_key": "sk-claude", "enabled": False}
        manager.nbi_config.acp_settings = {"api_key": "sk-acp", "enabled": False}
        # The stored model entries travel in the response too, apart from the
        # model lists; a mock here would hide a leak through them.
        manager.nbi_config.chat_model = {
            "provider": "openai-compatible",
            "model": "m",
            "properties": [{"id": "api_key", "value": "sk-stored-chat"}],
        }
        manager.nbi_config.inline_completion_model = {
            "provider": "openai-compatible",
            "model": "m",
            "properties": [{"id": "api_key", "value": "sk-stored-inline"}],
        }
        monkeypatch.setattr(ext_module, "ai_service_manager", manager)
        # Capture the dict before it is serialized; most fields are mocks.
        monkeypatch.setattr(ext_module.json, "dumps", lambda obj, *a, **k: obj)
        handler = MagicMock()
        handler.tour_config_path = ""
        handler.string_overrides = {}
        for name in (
            "disabled_tools",
            "disabled_providers",
            "disabled_coding_agent_launchers",
            "additional_skipped_workspace_directories",
        ):
            setattr(handler, name, [])

        ext_module.GetCapabilitiesHandler.get(handler)
        response = handler.finish.call_args[0][0]

        for models in (response["chat_models"], response["inline_completion_models"]):
            key = next(p for p in models[0]["properties"] if p["id"] == "api_key")
            assert key["value"] == SECRET_MASK
        assert response["claude_settings"]["api_key"] == SECRET_MASK
        assert response["acp_settings"]["api_key"] == SECRET_MASK
        for stored in (response["chat_model"], response["inline_completion_model"]):
            assert stored["properties"] == [{"id": "api_key", "value": SECRET_MASK}]
            assert stored["provider"] == "openai-compatible"
        for secret in (
            "sk-chat",
            "sk-inline",
            "sk-claude",
            "sk-acp",
            "sk-stored-chat",
            "sk-stored-inline",
        ):
            assert secret not in repr(response)
