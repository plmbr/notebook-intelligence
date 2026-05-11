# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Tests for the ClaudeMCPManager and the management policy gate."""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import notebook_intelligence.extension as ext_module
from notebook_intelligence.claude_mcp_manager import (
    ClaudeMCPManager,
    ClaudeMCPServer,
)
from notebook_intelligence.extension import (
    ClaudeMCPBaseHandler,
    ClaudeMCPListHandler,
)


@pytest.fixture
def claude_home(tmp_path, monkeypatch):
    """Stand up a fake $HOME with a populated `~/.claude.json`."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def working_dir(tmp_path):
    cwd = tmp_path / "project"
    cwd.mkdir()
    return cwd


def _write_claude_json(home: Path, doc: dict) -> None:
    (home / ".claude.json").write_text(json.dumps(doc), encoding="utf-8")


class TestClaudeMCPManagerListServers:
    def test_empty_when_no_config(self, claude_home, working_dir):
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        assert manager.list_servers() == []

    def test_user_scope_servers_round_trip(self, claude_home, working_dir):
        _write_claude_json(
            claude_home,
            {
                "mcpServers": {
                    "voicemode": {
                        "type": "stdio",
                        "command": "uvx",
                        "args": ["--refresh", "voice-mode"],
                        "env": {},
                    },
                    "sentry": {
                        "type": "http",
                        "url": "https://mcp.sentry.dev/mcp",
                        "headers": {"X-Tenant": "acme"},
                    },
                }
            },
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        servers = manager.list_servers()
        names = [(s.name, s.scope, s.transport) for s in servers]
        assert names == [
            ("sentry", "user", "http"),
            ("voicemode", "user", "stdio"),
        ]
        sentry = next(s for s in servers if s.name == "sentry")
        assert sentry.url == "https://mcp.sentry.dev/mcp"
        assert sentry.headers == {"X-Tenant": "acme"}
        voicemode = next(s for s in servers if s.name == "voicemode")
        assert voicemode.command == "uvx"
        assert voicemode.args == ["--refresh", "voice-mode"]

    def test_local_scope_keyed_by_working_dir(self, claude_home, working_dir):
        _write_claude_json(
            claude_home,
            {
                "projects": {
                    str(working_dir): {
                        "mcpServers": {
                            "playwright": {
                                "type": "stdio",
                                "command": "npx",
                                "args": ["-y", "@playwright/mcp@latest"],
                            }
                        }
                    },
                    "/some/other/project": {
                        "mcpServers": {
                            "should-not-appear": {
                                "type": "stdio",
                                "command": "x",
                            }
                        }
                    },
                }
            },
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        servers = manager.list_servers()
        assert [(s.name, s.scope) for s in servers] == [("playwright", "local")]

    def test_project_scope_from_dot_mcp_json(self, claude_home, working_dir):
        (working_dir / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "shared": {
                            "type": "stdio",
                            "command": "shared-cmd",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        servers = manager.list_servers()
        assert [(s.name, s.scope) for s in servers] == [("shared", "project")]

    def test_all_three_scopes_merged(self, claude_home, working_dir):
        _write_claude_json(
            claude_home,
            {
                "mcpServers": {
                    "u-srv": {"type": "stdio", "command": "u"},
                },
                "projects": {
                    str(working_dir): {
                        "mcpServers": {
                            "l-srv": {"type": "stdio", "command": "l"},
                        }
                    }
                },
            },
        )
        (working_dir / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"p-srv": {"type": "stdio", "command": "p"}}}),
            encoding="utf-8",
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        scopes = {s.name: s.scope for s in manager.list_servers()}
        assert scopes == {"u-srv": "user", "l-srv": "local", "p-srv": "project"}

    def test_unknown_transport_passes_through(self, claude_home, working_dir):
        _write_claude_json(
            claude_home,
            {"mcpServers": {"weird": {"type": "websocket", "url": "wss://x"}}},
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        srv = manager.list_servers()[0]
        assert srv.transport == "websocket"


class TestClaudeMCPManagerWrites:
    def test_add_returns_canonical_record_when_post_read_succeeds(
        self, claude_home, working_dir, monkeypatch
    ):
        """When the post-add re-read finds the freshly-written server, the
        canonical record (parsed from disk) is returned — *not* the
        synthesized fallback. This pins the preference: a regression that
        always synthesized would silently lose any field-level rewriting
        Claude does (e.g. inferring transport from the URL)."""
        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )

        async def fake_subprocess(*argv, **kwargs):
            # Simulate Claude actually writing the server to ~/.claude.json.
            doc = {
                "mcpServers": {
                    "my-srv": {
                        "type": "stdio",
                        "command": "claude-rewrote-this",
                        "args": ["--from", "claude"],
                        "env": {"CLAUDE": "added"},
                    }
                }
            }
            (claude_home / ".claude.json").write_text(json.dumps(doc))
            proc = MagicMock()

            async def communicate():
                return (b"", b"")

            proc.communicate = communicate
            proc.returncode = 0
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        result = asyncio.run(
            manager.add_server(
                name="my-srv",
                scope="user",
                transport="stdio",
                command_or_url="user-supplied-cmd",
                args=["--user-arg"],
            )
        )
        # Canonical fields from disk, not synthesized from inputs.
        assert result.command == "claude-rewrote-this"
        assert result.args == ["--from", "claude"]
        assert result.env == {"CLAUDE": "added"}

    @pytest.mark.parametrize("scope", ["user", "project", "local"])
    def test_add_invokes_cli_with_correct_args(
        self, claude_home, working_dir, scope, monkeypatch
    ):
        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )
        captured: dict = {}

        async def fake_subprocess(*argv, **kwargs):
            captured["argv"] = list(argv)
            captured["cwd"] = kwargs.get("cwd")
            proc = MagicMock()

            async def communicate():
                return (b"ok", b"")

            proc.communicate = communicate
            proc.returncode = 0
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

        # The post-add re-read should find the server too.
        _write_claude_json(claude_home, {"mcpServers": {}})
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        result = asyncio.run(
            manager.add_server(
                name="my-srv",
                scope=scope,
                transport="stdio",
                command_or_url="npx",
                args=["-y", "pkg"],
                env={"K": "v"},
            )
        )
        assert captured["argv"][0] == "/usr/local/bin/claude"
        assert "mcp" in captured["argv"]
        assert "add" in captured["argv"]
        assert "--scope" in captured["argv"]
        scope_idx = captured["argv"].index("--scope")
        assert captured["argv"][scope_idx + 1] == scope
        assert "-e" in captured["argv"]
        assert "K=v" in captured["argv"]
        assert captured["argv"][-3:] == ["npx", "--", "-y"] or captured["argv"][
            -4:
        ] == ["npx", "--", "-y", "pkg"]
        # When the CLI succeeds but our re-read finds nothing, we synthesize
        # from the inputs rather than 500.
        assert result.name == "my-srv"
        assert result.scope == scope

    @pytest.mark.parametrize(
        "env_key",
        ["-flag", "--inject", "BAD=KEY"],
    )
    def test_add_rejects_env_key_that_could_smuggle_flag(
        self, claude_home, working_dir, env_key
    ):
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        with pytest.raises(ValueError, match="env key"):
            asyncio.run(
                manager.add_server(
                    name="s",
                    scope="user",
                    transport="stdio",
                    command_or_url="npx",
                    env={env_key: "v"},
                )
            )

    @pytest.mark.parametrize(
        "header_key",
        ["-flag", "--inject", "Bad:Name"],
    )
    def test_add_rejects_header_name_that_could_smuggle_flag(
        self, claude_home, working_dir, header_key
    ):
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        with pytest.raises(ValueError, match="header name"):
            asyncio.run(
                manager.add_server(
                    name="s",
                    scope="user",
                    transport="http",
                    command_or_url="https://example.com",
                    headers={header_key: "v"},
                )
            )

    @pytest.mark.parametrize("transport", ["sse", "http"])
    @pytest.mark.parametrize(
        "bad_url",
        [
            "http://example.com",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
            "ftp://example.com",
        ],
    )
    def test_add_rejects_non_https_network_transport(
        self, claude_home, working_dir, transport, bad_url
    ):
        # SSRF defense: sse/http transports must be https only.
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        with pytest.raises(ValueError, match="https"):
            asyncio.run(
                manager.add_server(
                    name="s",
                    scope="user",
                    transport=transport,
                    command_or_url=bad_url,
                )
            )

    def test_remove_invokes_cli(self, claude_home, working_dir, monkeypatch):
        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )
        captured: dict = {}

        async def fake_subprocess(*argv, **kwargs):
            captured["argv"] = list(argv)
            proc = MagicMock()

            async def communicate():
                return (b"", b"")

            proc.communicate = communicate
            proc.returncode = 0
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

        manager = ClaudeMCPManager(working_dir=str(working_dir))
        asyncio.run(manager.remove_server("my-srv", "user"))
        assert captured["argv"][1:] == [
            "mcp",
            "remove",
            "--scope",
            "user",
            "my-srv",
        ]

    def test_cli_failure_raises_with_stderr(
        self, claude_home, working_dir, monkeypatch
    ):
        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )

        async def fake_subprocess(*argv, **kwargs):
            proc = MagicMock()

            async def communicate():
                return (b"", b"already exists")

            proc.communicate = communicate
            proc.returncode = 1
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

        manager = ClaudeMCPManager(working_dir=str(working_dir))
        with pytest.raises(ValueError, match="already exists"):
            asyncio.run(manager.remove_server("name", "user"))

    def test_missing_cli_raises_filenotfound(
        self, claude_home, working_dir, monkeypatch
    ):
        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: None,
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        with pytest.raises(FileNotFoundError):
            asyncio.run(manager.remove_server("name", "user"))

    def test_leading_dash_name_rejected(self, claude_home, working_dir, monkeypatch):
        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        with pytest.raises(ValueError, match="leading '-'"):
            asyncio.run(
                manager.add_server(
                    name="--scope=user",
                    scope="user",
                    transport="stdio",
                    command_or_url="x",
                )
            )

    def test_leading_dash_command_rejected(
        self, claude_home, working_dir, monkeypatch
    ):
        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        with pytest.raises(ValueError, match="leading '-'"):
            asyncio.run(
                manager.add_server(
                    name="srv",
                    scope="user",
                    transport="stdio",
                    command_or_url="--whatever",
                )
            )


class TestRedactArgvForLog:
    def test_redacts_env_values(self):
        from notebook_intelligence._claude_cli import redact_argv_for_log as _redact_argv_for_log

        argv = ["claude", "mcp", "add", "-e", "API_KEY=sk-secret", "name", "cmd"]
        assert _redact_argv_for_log(argv) == [
            "claude",
            "mcp",
            "add",
            "-e",
            "<redacted>",
            "name",
            "cmd",
        ]

    def test_redacts_header_values(self):
        from notebook_intelligence._claude_cli import redact_argv_for_log as _redact_argv_for_log

        argv = ["claude", "mcp", "add", "-H", "Authorization: Bearer abc"]
        assert _redact_argv_for_log(argv)[-2:] == ["-H", "<redacted>"]

    def test_passes_through_non_secrets(self):
        from notebook_intelligence._claude_cli import redact_argv_for_log as _redact_argv_for_log

        argv = ["claude", "mcp", "add", "--scope", "user", "name", "npx"]
        assert _redact_argv_for_log(argv) == argv


class TestLockSerialization:
    """Two concurrent writes against the (process-shared) lock must not
    interleave at the subprocess layer."""

    def test_concurrent_add_server_calls_are_serialized(
        self, claude_home, working_dir, monkeypatch
    ):
        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )
        events: list[str] = []

        async def fake_subprocess(*argv, **kwargs):
            proc = MagicMock()
            # `claude mcp add ... <name> <commandOrUrl>` — name is second-to-last.
            tag = argv[-2]

            async def communicate():
                events.append(f"start:{tag}")
                await asyncio.sleep(0.01)
                events.append(f"end:{tag}")
                return (b"", b"")

            proc.communicate = communicate
            proc.returncode = 0
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)

        async def driver():
            m1 = ClaudeMCPManager(working_dir=str(working_dir))
            m2 = ClaudeMCPManager(working_dir=str(working_dir))
            await asyncio.gather(
                m1.add_server(name="A", scope="user", transport="stdio", command_or_url="x"),
                m2.add_server(name="B", scope="user", transport="stdio", command_or_url="y"),
            )

        asyncio.run(driver())
        assert len(events) == 4
        assert events[0].startswith("start:")
        assert events[1] == events[0].replace("start:", "end:")
        assert events[2].startswith("start:")
        assert events[3] == events[2].replace("start:", "end:")


# Per-family policy-gate coverage lives in `tests/test_policy_gate.py`,
# parametrized across SkillsBaseHandler / ClaudeMCPBaseHandler /
# PluginsBaseHandler.
