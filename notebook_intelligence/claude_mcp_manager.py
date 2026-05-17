# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Read/write Claude Code's MCP server configuration.

Reads come from the JSON config files Claude maintains itself:

  - User scope:    ``~/.claude.json`` → top-level ``mcpServers``
  - Local scope:   ``~/.claude.json`` → ``projects.<cwd>.mcpServers``
  - Project scope: ``<cwd>/.mcp.json``

Writes go through ``claude mcp add`` / ``claude mcp remove`` so Claude
remains the source of truth for any side effects (project-trust prompts,
oauth bookkeeping, etc.). The file-based reads are decoupled from the CLI's
``claude mcp list`` output because that command does live health checks
that are slow and unstructured (no ``--json``).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Optional

from notebook_intelligence._claude_cli import (
    CLAUDE_SCOPES,
    reject_flag_smuggling,
    run_claude_cli,
    validate_scope,
)
from notebook_intelligence.config import _atomic_write_json

log = logging.getLogger(__name__)

ClaudeMCPScope = Literal["user", "project", "local"]
VALID_TRANSPORTS: tuple[str, ...] = ("stdio", "sse", "http")

CLI_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class ClaudeMCPServer:
    name: str
    scope: ClaudeMCPScope
    transport: str  # "stdio" | "sse" | "http"
    command: str = ""  # stdio
    args: list[str] = field(default_factory=list)  # stdio
    env: dict[str, str] = field(default_factory=dict)  # stdio
    url: str = ""  # sse | http
    headers: dict[str, str] = field(default_factory=dict)  # sse | http
    # Workspace-level disable, sourced from
    # `~/.claude.json` → projects.<cwd>.disabledMcpServers[]. Independent of
    # scope: the list is just server names, so the same flag applies to a
    # `user`-scope server even though it's a workspace-level opt-out.
    disabled_for_workspace: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "scope": self.scope,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
            "url": self.url,
            "headers": dict(self.headers),
            "disabled_for_workspace": self.disabled_for_workspace,
        }


def _read_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to read Claude MCP config %s: %s", path, exc)
        return None


def _coerce_str_dict(d: Optional[dict]) -> dict[str, str]:
    """Stringify keys/values; drop None values so they don't surface as the
    string "None" in the UI."""
    if not isinstance(d, dict):
        return {}
    return {str(k): str(v) for k, v in d.items() if v is not None}


def _coerce_server(name: str, raw: dict, scope: ClaudeMCPScope) -> Optional[ClaudeMCPServer]:
    if not isinstance(raw, dict):
        return None
    transport = raw.get("type") or "stdio"
    if transport not in VALID_TRANSPORTS:
        # Unknown transport — pass through untouched so the UI can show it
        # rather than silently dropping it.
        transport = str(transport)
    return ClaudeMCPServer(
        name=name,
        scope=scope,
        transport=transport,
        command=str(raw.get("command", "")),
        args=list(raw.get("args") or []),
        env=_coerce_str_dict(raw.get("env")),
        url=str(raw.get("url", "")),
        headers=_coerce_str_dict(raw.get("headers")),
    )


def _gather_from_dict(
    block: Optional[dict], scope: ClaudeMCPScope
) -> Iterable[ClaudeMCPServer]:
    if not isinstance(block, dict):
        return ()
    out: list[ClaudeMCPServer] = []
    for name, raw in block.items():
        srv = _coerce_server(str(name), raw, scope)
        if srv is not None:
            out.append(srv)
    return out


class ClaudeMCPManager:
    # Class-level so the lock is shared across all ClaudeMCPManager instances
    # within this process. Handlers construct a fresh manager per request,
    # so an instance lock wouldn't actually serialize anything. Claude's
    # CLI does read-modify-write on `~/.claude.json` without a lockfile, so
    # two in-flight `add`s from the same NBI server can clobber.
    _write_lock = asyncio.Lock()

    def __init__(self, working_dir: Optional[str] = None):
        self._working_dir = Path(working_dir) if working_dir else Path.cwd()
        self._user_config_path = Path.home() / ".claude.json"

    # --- reads ---------------------------------------------------------

    def list_servers(self) -> list[ClaudeMCPServer]:
        """Enumerate user + local + project scope servers visible to Claude."""
        servers: list[ClaudeMCPServer] = []
        user_doc = _read_json(self._user_config_path) or {}

        servers.extend(_gather_from_dict(user_doc.get("mcpServers"), "user"))

        # Local scope is keyed by absolute working-dir path under `projects`.
        projects = user_doc.get("projects") or {}
        project_block = projects.get(str(self._working_dir)) or {}
        servers.extend(_gather_from_dict(project_block.get("mcpServers"), "local"))

        # Project scope: ``<cwd>/.mcp.json`` with top-level ``mcpServers``.
        project_doc = _read_json(self._working_dir / ".mcp.json") or {}
        servers.extend(_gather_from_dict(project_doc.get("mcpServers"), "project"))

        disabled_names = self._read_disabled_names(project_block)
        if disabled_names:
            servers = [
                dataclasses.replace(s, disabled_for_workspace=s.name in disabled_names)
                for s in servers
            ]

        servers.sort(key=lambda s: (s.name, s.scope))
        return servers

    @staticmethod
    def _read_disabled_names(project_block: dict) -> set[str]:
        raw = project_block.get("disabledMcpServers") if isinstance(project_block, dict) else None
        if not isinstance(raw, list):
            return set()
        return {str(item) for item in raw if isinstance(item, str)}

    def get_server(self, name: str, scope: ClaudeMCPScope) -> Optional[ClaudeMCPServer]:
        for srv in self.list_servers():
            if srv.name == name and srv.scope == scope:
                return srv
        return None

    # --- writes (CLI shell-outs) ---------------------------------------

    async def add_server(
        self,
        *,
        name: str,
        scope: ClaudeMCPScope,
        transport: str,
        command_or_url: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> ClaudeMCPServer:
        """Run ``claude mcp add`` and return the persisted record."""
        validate_scope(scope)
        if transport not in VALID_TRANSPORTS:
            raise ValueError(
                f"Invalid transport {transport!r}; expected one of {VALID_TRANSPORTS}"
            )
        if not name:
            raise ValueError("Missing server name")
        if not command_or_url:
            raise ValueError("Missing command or URL")
        reject_flag_smuggling("name", name)
        reject_flag_smuggling("command_or_url", command_or_url)
        # For network transports, require HTTPS — `http://`/`file://`/etc.
        # would let a user point Claude at internal endpoints (SSRF) or
        # exfil credentials in plaintext. Stdio is a subprocess, not a URL.
        if transport in ("sse", "http"):
            scheme = command_or_url.split(":", 1)[0].lower()
            if scheme != "https":
                raise ValueError(
                    f"Transport {transport!r} requires https:// URL; got {scheme!r}"
                )
        # The CLI parses `-e KEY=VALUE` and `-H NAME: VALUE` as the next
        # positional argv; a key like `--inject` would either break the
        # CLI's parser or smuggle in a side-flag depending on version. The
        # separator (`=` for env, `:` for headers) is also reserved.
        for key in (env or {}):
            if not key or key.startswith("-") or "=" in key:
                raise ValueError(f"Invalid env key {key!r}")
        for key in (headers or {}):
            if not key or key.startswith("-") or ":" in key:
                raise ValueError(f"Invalid header name {key!r}")

        tail = ["mcp", "add", "--scope", scope, "--transport", transport]
        for key, value in (env or {}).items():
            tail.extend(["-e", f"{key}={value}"])
        for key, value in (headers or {}).items():
            tail.extend(["-H", f"{key}: {value}"])
        tail.append(name)
        tail.append(command_or_url)
        if args:
            # `--` sentinel keeps Claude from re-parsing user-supplied args
            # as flags; `reject_flag_smuggling` is therefore not needed for
            # individual `args` entries.
            tail.append("--")
            tail.extend(args)

        async with self._write_lock:
            await self._run_cli(tail)
        srv = self.get_server(name, scope)
        if srv is None:
            # Surfaced if Claude wrote elsewhere or our reads missed it. The CLI
            # already succeeded, so don't 500 — synthesize from the inputs.
            # Logged as a warning so an operator notices a real read/write
            # divergence (cwd mismatch, scope misroute, race).
            log.warning(
                "claude mcp add succeeded but post-add read missed %r in %s scope; "
                "returning synthesized record",
                name,
                scope,
            )
            return ClaudeMCPServer(
                name=name,
                scope=scope,
                transport=transport,
                command=command_or_url if transport == "stdio" else "",
                args=list(args or []),
                env=dict(env or {}),
                url=command_or_url if transport in ("sse", "http") else "",
                headers=dict(headers or {}),
            )
        return srv

    async def set_server_disabled(self, name: str, disabled: bool) -> ClaudeMCPServer:
        """Toggle the workspace-level disable flag for ``name``.

        Edits ``~/.claude.json`` in place. The flag is workspace-wide (a single
        list of names under the current working directory's ``projects``
        entry), so scope is not part of the key; passing the same name from a
        user/local/project row produces the same write.
        """
        if not name:
            raise ValueError("Missing server name")
        async with self._write_lock:
            self._mutate_disabled_list(name, disabled)
        matches = [s for s in self.list_servers() if s.name == name]
        if matches:
            return matches[0]
        # No definition of `name` is visible from the current cwd. The write
        # still succeeded (a future definition would inherit the disabled
        # flag), so synthesize a minimal record reflecting the new state.
        return ClaudeMCPServer(
            name=name,
            scope="user",
            transport="stdio",
            disabled_for_workspace=disabled,
        )

    def _mutate_disabled_list(self, name: str, disabled: bool) -> None:
        """Atomically update ``projects.<cwd>.disabledMcpServers`` in
        ``~/.claude.json``. Preserves all other keys verbatim."""
        path = self._user_config_path
        doc: dict
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as fp:
                    doc = json.load(fp)
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Could not parse {path}; refusing to overwrite: {exc}"
                ) from exc
            if not isinstance(doc, dict):
                raise ValueError(
                    f"{path} root must be a JSON object; got {type(doc).__name__}"
                )
        else:
            doc = {}

        projects = doc.setdefault("projects", {})
        if not isinstance(projects, dict):
            raise ValueError(f"{path}: `projects` must be an object")
        cwd_key = str(self._working_dir)
        project_block = projects.setdefault(cwd_key, {})
        if not isinstance(project_block, dict):
            raise ValueError(f"{path}: `projects.{cwd_key}` must be an object")
        current = project_block.get("disabledMcpServers")
        if isinstance(current, list):
            disabled_list = [str(x) for x in current if isinstance(x, str)]
        else:
            disabled_list = []
        present = name in disabled_list
        if disabled and not present:
            disabled_list.append(name)
        elif not disabled and present:
            disabled_list = [x for x in disabled_list if x != name]
        project_block["disabledMcpServers"] = disabled_list

        # Reuse the symlink/mode/parent-dir-fsync atomic-write helper from
        # config.py so all on-disk config edits share the same durability
        # contract.
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(str(path), doc)

    async def remove_server(self, name: str, scope: ClaudeMCPScope) -> None:
        validate_scope(scope)
        if not name:
            raise ValueError("Missing server name")
        reject_flag_smuggling("name", name)
        async with self._write_lock:
            await self._run_cli(["mcp", "remove", "--scope", scope, name])

    # --- internals -----------------------------------------------------

    async def _run_cli(self, tail: list[str]) -> str:
        return await run_claude_cli(
            tail,
            cwd=str(self._working_dir),
            timeout=CLI_TIMEOUT_SECONDS,
            label="claude mcp",
        )
