# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""ConfigHandler.post keeps ``claude_settings`` keys the settings panel does
not send.

The Claude settings panel posts a fixed set of keys on mount. Replacing the
stored dict with that payload erased any key the panel does not render, such
as ``jupyter_ui_tools_external``, which is set by hand in config.json. The
handler now merges the POST onto the stored value, and re-reads config.json
first so a hand edit made while the server runs is not overwritten.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from notebook_intelligence.claude import ClaudeCodeChatParticipant
from notebook_intelligence.feature_flags import (
    CLAUDE_CODE_TOOLS_ID,
    JUPYTER_UI_TOOLS_ID,
    POLICY_FORCE_OFF,
    POLICY_FORCE_ON,
)


# What the Claude settings tab sends when it mounts (settings-panel.tsx).
PANEL_PAYLOAD = {
    "enabled": True,
    "chat_model": "",
    "inline_chat_model": "",
    "inline_completion_model": "",
    "api_key": "",
    "base_url": "",
    "setting_sources": ["user"],
    "tools": [],
    "continue_conversation": False,
    "show_turn_usage": False,
}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


@pytest.fixture
def config(mock_nbi_config, tmp_path):
    """Point every file NBIConfig.load() reads into tmp_path, so the handler's
    reload sees only what a test writes."""
    mock_nbi_config.env_config_file = str(tmp_path / "env" / "config.json")
    mock_nbi_config.env_mcp_file = str(tmp_path / "env" / "mcp.json")
    mock_nbi_config.deprecated_env_config_file = str(tmp_path / "deprecated-env.json")
    mock_nbi_config.deprecated_user_config_file = str(tmp_path / "deprecated-user.json")
    mock_nbi_config.user_config = {}
    return mock_nbi_config


def _store(config, **user_config):
    """Config the server is running with: in memory and on disk."""
    config.user_config = json.loads(json.dumps(user_config))
    _write_json(config.user_config_file, user_config)


def _hand_edit(config, **user_config):
    """Rewrite config.json on disk only, as an edit made while the server runs."""
    _write_json(config.user_config_file, user_config)


def _on_disk(config):
    with open(config.user_config_file) as f:
        return json.load(f)


def _manager(config, participant=None):
    return SimpleNamespace(
        nbi_config=config,
        default_chat_participant=participant,
        update_models_from_config=MagicMock(),
        restart_acp_client=MagicMock(),
    )


def _post(config, body, feature_policies=None, string_overrides=None, manager=None):
    """POST ``body`` and return the ``claude_settings`` written to disk."""
    from notebook_intelligence.extension import ConfigHandler

    handler = MagicMock(spec=ConfigHandler)
    handler.request = MagicMock()
    handler.request.body = json.dumps(body).encode()
    handler.feature_policies = feature_policies or {}
    handler.string_overrides = string_overrides or {}
    with patch("notebook_intelligence.extension.ai_service_manager", manager or _manager(config)), \
         patch("notebook_intelligence.extension.perf.configure"):
        ConfigHandler.post(handler)
    handler.finish.assert_called_once_with("{}")
    return _on_disk(config).get("claude_settings")


class TestClaudeSettingsPostMergesStoredKeys:
    def test_a_hand_set_key_survives_the_panel_payload(self, config):
        _store(config, claude_settings={
            "enabled": True,
            "jupyter_ui_tools_external": True,
            "show_turn_usage": True,
        })

        stored = _post(config, {"claude_settings": PANEL_PAYLOAD})

        assert stored["jupyter_ui_tools_external"] is True
        assert stored["show_turn_usage"] is False

    def test_posted_keys_still_override_stored_values(self, config):
        _store(config, claude_settings={
            "chat_model": "claude-old",
            "show_turn_usage": True,
        })

        stored = _post(config, {
            "claude_settings": {**PANEL_PAYLOAD, "chat_model": "claude-new"},
        })

        assert stored["chat_model"] == "claude-new"
        assert stored["show_turn_usage"] is False

    def test_a_posted_list_replaces_the_stored_list(self, config):
        """The merge is shallow, so unchecking a tool in the panel sticks."""
        _store(config, claude_settings={
            "tools": [CLAUDE_CODE_TOOLS_ID, JUPYTER_UI_TOOLS_ID],
            "setting_sources": ["user", "project"],
        })

        stored = _post(config, {"claude_settings": {
            **PANEL_PAYLOAD,
            "tools": [CLAUDE_CODE_TOOLS_ID],
            "setting_sources": ["user"],
        }})

        assert stored["tools"] == [CLAUDE_CODE_TOOLS_ID]
        assert stored["setting_sources"] == ["user"]

    def test_a_partial_post_keeps_the_stored_lists(self, config):
        """apply_claude_policies always writes tools and setting_sources, so
        the merge has to run before it or a POST without them empties both."""
        _store(config, claude_settings={
            "enabled": True,
            "tools": [CLAUDE_CODE_TOOLS_ID],
            "setting_sources": ["user", "project"],
        })

        stored = _post(config, {"claude_settings": {"show_turn_usage": True}})

        assert stored["tools"] == [CLAUDE_CODE_TOOLS_ID]
        assert stored["setting_sources"] == ["user", "project"]
        assert stored["show_turn_usage"] is True

    def test_a_forced_tool_is_added_to_the_stored_tools(self, config):
        _store(config, claude_settings={
            "enabled": True,
            "tools": [CLAUDE_CODE_TOOLS_ID],
        })

        stored = _post(
            config, {"claude_settings": {"enabled": True}},
            feature_policies={"claude_jupyter_ui_tools": POLICY_FORCE_ON},
        )

        assert stored["tools"] == [CLAUDE_CODE_TOOLS_ID, JUPYTER_UI_TOOLS_ID]

    def test_a_policy_still_clamps_a_stored_value(self, config):
        """Policies apply to the merged dict, so a stored value the POST does
        not mention cannot slip past a forced policy."""
        _store(config, claude_settings={
            "enabled": True,
            "continue_conversation": True,
        })

        stored = _post(
            config, {"claude_settings": {"enabled": True}},
            feature_policies={"claude_continue_conversation": POLICY_FORCE_OFF},
        )

        assert stored["continue_conversation"] is False

    def test_env_api_key_still_scrubs_a_stale_stored_key(self, config):
        """The ANTHROPIC_API_KEY scrub applies to the merged dict, so a stored
        credential is still kept out of config.json."""
        _store(config, claude_settings={"api_key": "sk-stale"})

        stored = _post(
            config, {"claude_settings": {"enabled": True}},
            string_overrides={"claude_api_key": "sk-env"},
        )

        assert stored["api_key"] == ""

    def test_an_environment_config_key_is_copied_into_the_user_config(self, config):
        """With no user value, NBIConfig.get falls back to the environment
        config, so the first POST copies its keys into the user config, as it
        already did for the keys the panel sends, rather than dropping them."""
        _write_json(config.env_config_file, {
            "claude_settings": {"jupyter_ui_tools_external": True},
        })
        config.load()

        stored = _post(config, {"claude_settings": PANEL_PAYLOAD})

        assert stored["jupyter_ui_tools_external"] is True

    def test_acp_taking_over_keeps_a_hand_set_key(self, config):
        _store(
            config,
            claude_settings={"enabled": True, "jupyter_ui_tools_external": True},
            acp_settings={"enabled": False},
        )

        stored = _post(config, {
            "claude_settings": {**PANEL_PAYLOAD, "show_turn_usage": True},
            "acp_settings": {"enabled": True},
        })

        assert stored["enabled"] is False
        assert stored["jupyter_ui_tools_external"] is True
        assert stored["show_turn_usage"] is True

    def test_a_null_stored_value_is_replaced_by_the_post(self, config):
        _store(config, claude_settings=None)

        stored = _post(config, {"claude_settings": PANEL_PAYLOAD})

        assert stored["show_turn_usage"] is False

    def test_a_null_post_does_not_raise(self, config):
        _store(config, claude_settings={"enabled": True})

        _post(config, {"claude_settings": None})


class TestConfigPostReloadsFromDisk:
    def test_a_hand_edit_survives_the_claude_tab_payload(self, config):
        _store(config, claude_settings={"enabled": True, "show_turn_usage": True})
        _hand_edit(config, claude_settings={
            "enabled": True,
            "show_turn_usage": True,
            "jupyter_ui_tools_external": True,
        })

        stored = _post(config, {"claude_settings": PANEL_PAYLOAD})

        assert stored["jupyter_ui_tools_external"] is True
        assert stored["show_turn_usage"] is False

    def test_a_hand_edit_survives_a_post_without_claude_settings(self, config):
        """The General tab's mount POST sends no claude_settings but still
        saves the whole config, including mcp.json."""
        _store(config, claude_settings={"enabled": True})
        _hand_edit(
            config,
            claude_settings={"enabled": True, "jupyter_ui_tools_external": True},
            enable_explain_error=False,
        )
        _write_json(config.user_mcp_file, {"mcpServers": {"edited": {"command": "x"}}})

        _post(config, {"inline_completion_debouncer_delay": 350})

        on_disk = _on_disk(config)
        assert on_disk["inline_completion_debouncer_delay"] == 350
        assert on_disk["claude_settings"]["jupyter_ui_tools_external"] is True
        assert on_disk["enable_explain_error"] is False
        with open(config.user_mcp_file) as f:
            assert "edited" in json.load(f)["mcpServers"]

    def test_enabling_acp_wins_over_an_acp_enable_found_only_on_disk(self, config):
        """The exclusivity check compares against the running state, so ACP
        enabled on disk does not count as already on and lose the tie."""
        _store(
            config,
            claude_settings={"enabled": True},
            acp_settings={"enabled": False},
        )
        _hand_edit(
            config,
            claude_settings={"enabled": True},
            acp_settings={"enabled": True},
        )

        stored = _post(config, {"acp_settings": {"enabled": True}})

        assert stored["enabled"] is False
        assert _on_disk(config)["acp_settings"]["enabled"] is True

    def test_an_unchanged_acp_payload_does_not_restart_the_agent(self, config):
        """The ACP tab re-posts its values on mount. A disk edit made since the
        last load is not a change to the running agent."""
        running = {"enabled": True, "chat_model": "gpt-5"}
        _store(config, acp_settings=running)
        _hand_edit(config, acp_settings={"enabled": True, "chat_model": "gpt-5-codex"})
        manager = _manager(config)

        _post(config, {"acp_settings": running}, manager=manager)

        manager.restart_acp_client.assert_not_called()

    def test_a_changed_acp_payload_restarts_the_agent_even_if_disk_matches(self, config):
        _store(config, acp_settings={"enabled": True, "chat_model": "gpt-5"})
        new = {"enabled": True, "chat_model": "gpt-5-codex"}
        _hand_edit(config, acp_settings=new)
        manager = _manager(config)

        _post(config, {"acp_settings": new}, manager=manager)

        manager.restart_acp_client.assert_called_once()

    def test_a_claude_disable_found_on_disk_disconnects_the_live_client(self, config):
        """Enabling ACP when Claude was turned off on disk leaves no conflict
        to resolve, so the handler must still disconnect the running client."""
        _store(
            config,
            claude_settings={"enabled": True},
            acp_settings={"enabled": False},
        )
        _hand_edit(
            config,
            claude_settings={"enabled": False},
            acp_settings={"enabled": False},
        )
        participant = MagicMock(spec=ClaudeCodeChatParticipant)
        manager = _manager(config, participant)

        _post(config, {"acp_settings": {"enabled": True}}, manager=manager)

        participant.update_client_debounced.assert_called()
        manager.update_models_from_config.assert_called_once()

    def test_a_malformed_config_file_fails_without_overwriting_it(self, config):
        """A broken hand edit is left for the user to fix rather than replaced
        with the in-memory copy."""
        from notebook_intelligence.extension import ConfigHandler

        _store(config, claude_settings={"enabled": True})
        with open(config.user_config_file, "w") as f:
            f.write('{"claude_settings": {"enabled": true,}}')
        handler = MagicMock(spec=ConfigHandler)
        handler.request = MagicMock()
        handler.request.body = json.dumps({"enable_explain_error": True}).encode()
        handler.feature_policies = {}
        handler.string_overrides = {}

        with patch("notebook_intelligence.extension.ai_service_manager", _manager(config)), \
             patch("notebook_intelligence.extension.perf.configure"), \
             pytest.raises(json.JSONDecodeError):
            ConfigHandler.post(handler)

        with open(config.user_config_file) as f:
            assert f.read() == '{"claude_settings": {"enabled": true,}}'
