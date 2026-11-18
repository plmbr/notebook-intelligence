# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""MCP credentials, and the CLI and Claude-mode error text that may echo them,
must not reach the browser or the workspace in clear text."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from notebook_intelligence import extension as ext_module
from notebook_intelligence.claude_mcp_manager import ClaudeMCPServer
from notebook_intelligence.credential_mask import (
    SECRET_MASK,
    UnresolvedMaskError,
    mask_mcp_config,
    restore_masked_mcp_config,
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


class TestClaudeStreamErrorScrubbing:
    def test_inline_stream_error_marker_is_scrubbed(self, monkeypatch):
        from notebook_intelligence.claude import ClaudeChatModel

        monkeypatch.setenv("PROXY_API_KEY", "proxy-master-key-0042")
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
    def _proxy_key(self, monkeypatch):
        monkeypatch.setenv("PROXY_API_KEY", "proxy-master-key-0042")

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
