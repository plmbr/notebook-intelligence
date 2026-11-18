# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""MCP credentials must not reach the browser or the workspace in clear text."""

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


