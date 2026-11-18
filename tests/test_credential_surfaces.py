# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Credentials NBI stores must not reach the browser, the workspace, the
agent's file tools, or shell output in clear text."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import notebook_intelligence.built_in_toolsets as toolsets
from notebook_intelligence import extension as ext_module
from notebook_intelligence import util as util_mod
from notebook_intelligence.claude_mcp_manager import ClaudeMCPServer
from notebook_intelligence.credential_mask import (
    SECRET_MASK,
    UnresolvedMaskError,
    collect_stored_secrets,
    mask_mcp_config,
    restore_masked_mcp_config,
)
from notebook_intelligence.util import (
    is_protected_nbi_path,
    redact_env_secrets,
    set_stored_secret_provider,
)

MCP = {
    "mcpServers": {
        "remote": {
            "url": "https://mcp.example",
            "headers": {"Authorization": "Bearer tok-abcdef123456", "X-Tenant": "acme"},
        },
        "local": {
            "command": "uvx",
            "env": {"GITHUB_TOKEN": "ghp-local-secret-1", "LOG_LEVEL": "verbose-debug"},
        },
    }
}


class TestClaudeMcpWire:
    def _server(self):
        return ClaudeMCPServer(
            name="x",
            scope="user",
            transport="http",
            url="https://m",
            headers={"Authorization": "Bearer abc123", "X-Tenant": "acme"},
            env={"API_KEY": "k-secret-value"},
        )

    def test_wire_dict_masks_every_env_and_header_value(self):
        wire = self._server().to_wire_dict()
        assert wire["headers"] == {"Authorization": SECRET_MASK, "X-Tenant": SECRET_MASK}
        assert wire["env"] == {"API_KEY": SECRET_MASK}
        assert wire["url"] == "https://m"
        assert "abc123" not in json.dumps(wire)

    def test_internal_dict_keeps_the_values(self):
        assert self._server().to_dict()["headers"]["Authorization"] == "Bearer abc123"


class TestMcpEditorMask:
    def test_only_credential_named_values_are_masked(self):
        masked = mask_mcp_config(MCP)["mcpServers"]
        assert masked["remote"]["headers"] == {
            "Authorization": SECRET_MASK,
            "X-Tenant": "acme",
        }
        assert masked["local"]["env"] == {
            "GITHUB_TOKEN": SECRET_MASK,
            "LOG_LEVEL": "verbose-debug",
        }
        assert MCP["mcpServers"]["local"]["env"]["GITHUB_TOKEN"] == "ghp-local-secret-1"

    def test_masked_document_round_trips_to_the_original(self):
        assert restore_masked_mcp_config(mask_mcp_config(MCP), MCP) == MCP

    def test_an_edited_value_replaces_the_stored_one(self):
        posted = mask_mcp_config(MCP)
        posted["mcpServers"]["local"]["env"]["GITHUB_TOKEN"] = "ghp-new-value-22"
        restored = restore_masked_mcp_config(posted, MCP)
        assert restored["mcpServers"]["local"]["env"]["GITHUB_TOKEN"] == "ghp-new-value-22"

    def test_a_mask_with_nothing_stored_is_refused(self):
        posted = mask_mcp_config(MCP)
        posted["mcpServers"]["renamed"] = posted["mcpServers"].pop("remote")
        with pytest.raises(UnresolvedMaskError, match=r"renamed\.headers\.Authorization") as caught:
            restore_masked_mcp_config(posted, MCP)
        assert caught.value.names == ["renamed.headers.Authorization"]

    def test_non_server_documents_pass_through(self):
        assert mask_mcp_config({}) == {}
        assert restore_masked_mcp_config({"mcpServers": {}}, None) == {"mcpServers": {}}


class FakeConfig:
    def __init__(self, mcp):
        self.mcp = mcp
        self.user_mcp = None
        self.saved = False

    def load(self):
        pass

    def save(self):
        self.saved = True


def _handler():
    handler = MagicMock(spec=ext_module.MCPConfigFileHandler)
    handler.request = MagicMock()
    return handler


class TestMcpConfigHandler:
    @pytest.fixture
    def config(self, monkeypatch):
        config = FakeConfig(json.loads(json.dumps(MCP)))
        manager = SimpleNamespace(
            nbi_config=config,
            get_mcp_stdio_command_allowlist=lambda: [],
            update_mcp_servers=lambda: None,
        )
        monkeypatch.setattr(ext_module, "ai_service_manager", manager)
        return config

    def test_get_sends_no_credential(self, config):
        handler = _handler()
        ext_module.MCPConfigFileHandler.get.__wrapped__(handler)
        body = handler.finish.call_args[0][0]
        assert "tok-abcdef123456" not in body
        assert "ghp-local-secret-1" not in body
        assert "acme" in body

    def test_saving_the_masked_document_keeps_the_stored_values(self, config):
        handler = _handler()
        handler.request.body = json.dumps(mask_mcp_config(MCP)).encode()
        ext_module.MCPConfigFileHandler.post.__wrapped__(handler)
        assert config.saved
        assert config.user_mcp == MCP

    def test_an_unresolvable_mask_is_a_400_and_nothing_is_saved(self, config):
        posted = mask_mcp_config(MCP)
        posted["mcpServers"]["renamed"] = posted["mcpServers"].pop("remote")
        handler = _handler()
        handler.request.body = json.dumps(posted).encode()
        ext_module.MCPConfigFileHandler.post.__wrapped__(handler)
        handler.set_status.assert_called_with(400)
        message = json.loads(handler.finish.call_args[0][0])["message"]
        assert "renamed.headers.Authorization" in message
        assert "Enter the real value" in message
        assert not config.saved


@pytest.fixture
def home_root(tmp_path, monkeypatch):
    """A workspace that is the home directory, as when JupyterLab starts in ~."""
    monkeypatch.setenv("HOME", str(tmp_path))
    nbi = tmp_path / ".jupyter" / "nbi"
    nbi.mkdir(parents=True)
    (nbi / "config.json").write_text('{"claude_settings": {"api_key": "sk-REAL-9999"}}')
    (nbi / "mcp.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("api_key lives elsewhere\n")
    monkeypatch.setattr(util_mod, "_jupyter_root_dir", str(tmp_path))
    return tmp_path


def _run(tool, **kwargs):
    return asyncio.run(tool._tool_function(**kwargs))


class TestFileToolsRefuseNbiConfig:
    def test_read_file_refuses_config_and_still_reads_others(self, home_root):
        result = _run(toolsets.read_file, file_path=".jupyter/nbi/config.json")
        assert result == toolsets.PROTECTED_NBI_FILE_MESSAGE
        assert "REAL" not in result
        assert "elsewhere" in _run(toolsets.read_file, file_path="notes.txt")

    def test_write_tools_refuse_config(self, home_root):
        target = ".jupyter/nbi/mcp.json"
        assert _run(toolsets.write_to_file, file_path=target, content="x") == (
            toolsets.PROTECTED_NBI_FILE_MESSAGE
        )
        assert _run(
            toolsets.insert_content, file_path=target, line_number=1, content="x"
        ) == toolsets.PROTECTED_NBI_FILE_MESSAGE
        assert (home_root / ".jupyter/nbi/mcp.json").read_text() == "{}"

    def test_search_skips_config(self, home_root):
        result = _run(
            toolsets.search_files,
            pattern="**/*",
            directory=".",
            content_pattern="api_key",
        )
        assert "REAL" not in result
        assert "notes.txt" in result

    def test_a_symlink_to_config_is_refused(self, home_root):
        (home_root / "link.json").symlink_to(home_root / ".jupyter/nbi/config.json")
        assert _run(toolsets.read_file, file_path="link.json") == (
            toolsets.PROTECTED_NBI_FILE_MESSAGE
        )

    def test_editor_temp_copy_is_refused_wherever_it_is(self, home_root):
        (home_root / "nbi.mcp.temp.json").write_text("{}")
        assert is_protected_nbi_path(home_root / "nbi.mcp.temp.json")
        assert not is_protected_nbi_path(home_root / "notes.txt")


class TestStoredSecretRedaction:
    @pytest.fixture(autouse=True)
    def _clear(self):
        yield
        set_stored_secret_provider(None)

    def test_collects_keys_headers_and_secret_env_values(self):
        values = collect_stored_secrets(
            [
                {
                    "claude_settings": {"api_key": "sk-claude-1234"},
                    "acp_settings": {"api_key": "acp-key-12345"},
                    "chat_model": {
                        "properties": [
                            {"id": "api_key", "value": "proxy-key-98765"},
                            {"id": "base_url", "value": "https://proxy.example"},
                        ]
                    },
                }
            ],
            MCP,
        )
        assert {
            "sk-claude-1234",
            "acp-key-12345",
            "proxy-key-98765",
            "Bearer tok-abcdef123456",
            "tok-abcdef123456",
            "ghp-local-secret-1",
        } <= set(values)
        assert "https://proxy.example" not in values
        assert "acme" not in values and "verbose-debug" not in values

    @pytest.mark.parametrize(
        "placeholder", ["not-needed", "lm-studio", "Dummy-API-Key", "sk_no_key_required", "ollama"]
    )
    def test_placeholder_keys_are_not_collected(self, placeholder):
        values = collect_stored_secrets(
            [
                {
                    "claude_settings": {"api_key": placeholder},
                    "chat_model": {
                        "properties": [{"id": "api_key", "value": placeholder}]
                    },
                }
            ],
            {"mcpServers": {"s": {"headers": {"Authorization": f"Bearer {placeholder}"}}}},
        )
        assert placeholder not in values

    def test_placeholder_is_left_alone_in_shell_output(self):
        set_stored_secret_provider(
            lambda: collect_stored_secrets(
                [{"claude_settings": {"api_key": "not-needed"}}], None
            )
        )
        text = "the value is not-needed here"
        assert redact_env_secrets(text) == text

    def test_a_real_key_next_to_a_placeholder_is_still_collected(self):
        values = collect_stored_secrets(
            [
                {
                    "claude_settings": {"api_key": "not-needed"},
                    "acp_settings": {"api_key": "acp-key-12345"},
                }
            ],
            None,
        )
        assert values == ["acp-key-12345"]

    def test_shell_output_loses_a_key_without_a_known_prefix(self):
        text = '{"api_key": "litellm-master-key-9f8e7d6c"}'
        assert "litellm-master-key" in redact_env_secrets(text)
        set_stored_secret_provider(lambda: ["litellm-master-key-9f8e7d6c"])
        assert "litellm-master-key" not in redact_env_secrets(text)

    def test_a_failing_provider_does_not_break_redaction(self):
        def boom():
            raise RuntimeError("config unreadable")

        set_stored_secret_provider(boom)
        assert redact_env_secrets("hello") == "hello"


class TestCliErrorScrubbing:
    """`claude mcp add` takes env and header values as flags, and the
    handlers forward the CLI's error text to the browser."""

    def _manager(self, tmp_path, monkeypatch, stderr):
        from pathlib import Path

        from notebook_intelligence.claude_mcp_manager import ClaudeMCPManager

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )

        async def fake_subprocess(*argv, **kwargs):
            proc = MagicMock()

            async def communicate():
                return (b"", stderr)

            proc.communicate = communicate
            proc.returncode = 1
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
        project = tmp_path / "project"
        project.mkdir()
        return ClaudeMCPManager(working_dir=str(project))

    def test_header_and_env_values_are_scrubbed_from_the_error(
        self, tmp_path, monkeypatch
    ):
        stderr = (
            b"error: invalid header 'Authorization: Bearer tok-abcdef123456'; "
            b"env GITHUB_TOKEN=ghp-local-secret-1 rejected"
        )
        manager = self._manager(tmp_path, monkeypatch, stderr)
        with pytest.raises(ValueError) as caught:
            asyncio.run(
                manager.add_server(
                    name="srv",
                    scope="user",
                    transport="http",
                    command_or_url="https://mcp.example",
                    headers={"Authorization": "Bearer tok-abcdef123456"},
                    env={"GITHUB_TOKEN": "ghp-local-secret-1"},
                )
            )
        message = str(caught.value)
        assert "tok-abcdef123456" not in message
        assert "ghp-local-secret-1" not in message
        assert "invalid header" in message

    def test_stored_credentials_are_scrubbed_even_when_not_in_the_call(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "notebook_intelligence.util._stored_secret_provider",
            lambda: ["proxy-master-key-0042"],
        )
        manager = self._manager(
            tmp_path, monkeypatch, b"401 Received API Key = proxy-master-key-0042"
        )
        with pytest.raises(ValueError) as caught:
            asyncio.run(manager.remove_server("srv", "user"))
        assert "proxy-master-key-0042" not in str(caught.value)


class TestClaudeStreamErrorScrubbing:
    def test_inline_stream_error_marker_is_scrubbed(self, monkeypatch):
        from notebook_intelligence.claude import ClaudeChatModel

        monkeypatch.setattr(
            "notebook_intelligence.util._stored_secret_provider",
            lambda: ["proxy-master-key-0042"],
        )
        model = ClaudeChatModel.__new__(ClaudeChatModel)
        model._model_id = "claude-sonnet-test"
        model._model_name = "Claude Sonnet (test)"
        model._context_window = 200000
        model._supports_tools = True
        model._client = MagicMock()
        boom = RuntimeError("401 Received API Key = proxy-master-key-0042")
        model._client.messages.stream = MagicMock(side_effect=boom)
        response = MagicMock()

        with pytest.raises(RuntimeError):
            model.completions(
                messages=[{"role": "user", "content": "x"}], response=response
            )

        payload = response.stream.call_args_list[-1].args[0]
        assert "proxy-master-key-0042" not in repr(payload)
        assert "Stream interrupted" in payload["choices"][0]["delta"]["content"]
        assert "proxy-master-key-0042" not in payload["nbi_stream_error"]


class TestRedactionCaches:
    """The path check and the credential list are reused between calls; the
    reuse must not outlive a change that matters."""

    @pytest.fixture(autouse=True)
    def _clear(self):
        yield
        set_stored_secret_provider(None)

    def _counting_provider(self, values):
        calls = []

        def provider():
            calls.append(1)
            return list(values)

        return provider, calls

    def test_credentials_are_collected_once_across_many_lines(self):
        provider, calls = self._counting_provider(["litellm-master-key-9f8e7d6c"])
        set_stored_secret_provider(provider)
        for _ in range(50):
            assert "<redacted>" in redact_env_secrets("key litellm-master-key-9f8e7d6c")
        assert len(calls) == 1

    def test_invalidating_picks_up_a_changed_credential(self):
        values = ["first-secret-value-1"]
        set_stored_secret_provider(lambda: list(values))
        assert "first-secret-value-1" not in redact_env_secrets("first-secret-value-1")
        values[:] = ["second-secret-value-2"]
        util_mod.invalidate_stored_secret_cache()
        assert "second-secret-value-2" not in redact_env_secrets("second-secret-value-2")

    def test_config_save_and_load_invalidate(self, tmp_path):
        from notebook_intelligence.config import NBIConfig

        config = NBIConfig.__new__(NBIConfig)
        config.nbi_user_dir = str(tmp_path / "nbi")
        config.user_config_file = str(tmp_path / "nbi" / "config.json")
        config.user_mcp_file = str(tmp_path / "nbi" / "mcp.json")
        config.env_config_file = str(tmp_path / "env-config.json")
        config.env_mcp_file = str(tmp_path / "env-mcp.json")
        config.deprecated_env_config_file = str(tmp_path / "dep-env.json")
        config.deprecated_user_config_file = str(tmp_path / "dep-user.json")
        config.user_config, config.env_config = {}, {}
        config.user_mcp, config.env_mcp = {}, {}
        provider, calls = self._counting_provider(["litellm-master-key-9f8e7d6c"])
        set_stored_secret_provider(provider)

        redact_env_secrets("x")
        redact_env_secrets("x")
        assert len(calls) == 1
        config.save()
        redact_env_secrets("x")
        assert len(calls) == 2
        config.load()
        redact_env_secrets("x")
        assert len(calls) == 3

    def test_a_swapped_provider_is_never_served_stale_values(self, monkeypatch):
        set_stored_secret_provider(lambda: ["old-provider-secret-1"])
        redact_env_secrets("x")
        monkeypatch.setattr(
            util_mod, "_stored_secret_provider", lambda: ["new-provider-secret-2"]
        )
        assert "new-provider-secret-2" not in redact_env_secrets("new-provider-secret-2")

    def test_a_failing_provider_is_retried_not_cached(self):
        state = {"fail": True}

        def provider():
            if state["fail"]:
                raise RuntimeError("config unreadable")
            return ["recovered-secret-value"]

        set_stored_secret_provider(provider)
        assert redact_env_secrets("recovered-secret-value") == "recovered-secret-value"
        state["fail"] = False
        assert "recovered-secret-value" not in redact_env_secrets("recovered-secret-value")

    def test_a_newly_registered_protected_path_is_noticed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        extra = tmp_path / "elsewhere" / "extra-config.json"
        extra.parent.mkdir()
        extra.write_text("{}")
        assert not is_protected_nbi_path(extra)
        monkeypatch.setattr(
            util_mod, "_registered_protected_paths", set(util_mod._registered_protected_paths)
        )
        util_mod.register_protected_paths([extra])
        assert is_protected_nbi_path(extra)

    def test_a_repointed_symlink_is_noticed_after_the_ttl(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        nbi = tmp_path / ".jupyter" / "nbi"
        nbi.mkdir(parents=True)
        shared_a = tmp_path / "shared-a.json"
        shared_b = tmp_path / "shared-b.json"
        shared_a.write_text("{}")
        shared_b.write_text("{}")
        (nbi / "config.json").symlink_to(shared_a)
        monkeypatch.setattr(util_mod, "_PROTECTED_PATHS_CACHE_SECONDS", 0.0)
        assert is_protected_nbi_path(shared_a) and not is_protected_nbi_path(shared_b)
        (nbi / "config.json").unlink()
        (nbi / "config.json").symlink_to(shared_b)
        assert is_protected_nbi_path(shared_b)


class TestReviewFixes:
    @pytest.fixture(autouse=True)
    def _clear(self):
        yield
        set_stored_secret_provider(None)

    def test_bearer_placeholder_is_not_collected(self):
        values = collect_stored_secrets(
            [], {"mcpServers": {"s": {"headers": {"Authorization": "Bearer not-needed"}}}}
        )
        assert values == []

    def test_a_save_during_collection_is_not_cached(self):
        calls = []

        def provider():
            calls.append(1)
            if len(calls) == 1:
                # A config save lands while this walk is in progress.
                util_mod.invalidate_stored_secret_cache()
            return ["litellm-master-key-9f8e7d6c"]

        set_stored_secret_provider(provider)
        redact_env_secrets("x")
        redact_env_secrets("x")
        assert len(calls) == 2  # the first result predated the save
        redact_env_secrets("x")
        assert len(calls) == 2  # the second was cached normally

    def test_a_hard_link_to_the_config_is_protected(self, home_root):
        link = home_root / "innocent-name.json"
        import os

        os.link(home_root / ".jupyter/nbi/config.json", link)
        assert is_protected_nbi_path(link)
        assert _run(toolsets.read_file, file_path="innocent-name.json") == (
            toolsets.PROTECTED_NBI_FILE_MESSAGE
        )

    def test_config_save_drops_the_protected_cache(self, tmp_path):
        from notebook_intelligence.config import NBIConfig

        config = NBIConfig.__new__(NBIConfig)
        config.nbi_user_dir = str(tmp_path / "nbi")
        config.user_config_file = str(tmp_path / "nbi" / "config.json")
        config.user_mcp_file = str(tmp_path / "nbi" / "mcp.json")
        config.user_config, config.user_mcp = {}, {}
        is_protected_nbi_path(tmp_path / "x.json")
        assert util_mod._protected_paths_cache is not None
        config.save()
        assert util_mod._protected_paths_cache is None

    def test_a_mention_cannot_reach_the_config_through_a_symlink(self, home_root):
        from notebook_intelligence.chatbook_mentions import _safe_relative_path

        (home_root / "docs").mkdir()
        (home_root / "docs" / "notes.json").symlink_to(
            home_root / ".jupyter/nbi/config.json"
        )
        with pytest.raises(ValueError, match="unsafe mention path"):
            _safe_relative_path("docs/notes.json")
        assert _safe_relative_path("notes.txt").name == "notes.txt"


class TestClaudeChatErrorScrubbing:
    def _stream(self, participant):
        from notebook_intelligence.api import ChatResponse, MarkdownData
        from notebook_intelligence import i18n
        from tests.test_claude_client import _make_chat_request

        response = MagicMock(spec=ChatResponse, trans=i18n.english())
        asyncio.run(participant.handle_chat_request(_make_chat_request(), response))
        return [
            call.args[0].content
            for call in response.stream.call_args_list
            if isinstance(call.args[0], MarkdownData)
        ]

    @pytest.fixture(autouse=True)
    def _provider(self):
        set_stored_secret_provider(lambda: ["proxy-master-key-0042"])
        yield
        set_stored_secret_provider(None)

    def test_the_bail_out_string_is_scrubbed(self):
        from tests.test_claude_client import _make_participant

        participant = _make_participant()
        participant._client.query.return_value = "401 Received API Key = proxy-master-key-0042"
        messages = self._stream(participant)
        assert any("Claude agent error" in m for m in messages)
        assert "proxy-master-key-0042" not in " ".join(messages)

    def test_an_exception_is_scrubbed(self):
        from tests.test_claude_client import _make_participant

        participant = _make_participant()
        participant._client.query.side_effect = RuntimeError(
            "401 Received API Key = proxy-master-key-0042"
        )
        messages = self._stream(participant)
        assert any("Error" in m for m in messages)
        assert "proxy-master-key-0042" not in " ".join(messages)
