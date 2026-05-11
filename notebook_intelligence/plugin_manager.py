# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Wrapper around Claude Code's `claude plugin` CLI.

Plugin state is owned by Claude Code itself (under `~/.claude/plugins/`).
NBI shells out for both reads and writes:

  - `claude plugin list --json` → JSON array of installed plugins
  - `claude plugin marketplace list --json` → JSON array of marketplaces
  - `claude plugin install <plugin>[@marketplace] -s <scope>`
  - `claude plugin uninstall <plugin> -s <scope> -y`  (-y for non-TTY)
  - `claude plugin enable <plugin> [-s scope]`
  - `claude plugin disable <plugin> [-s scope]`
  - `claude plugin marketplace add <source> [--scope <scope>]`
  - `claude plugin marketplace remove <name>`

The CLI's JSON-output schema is not formally documented; the manager
forwards parsed objects to the frontend mostly untouched so newer Claude
releases that add fields don't get truncated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from typing import Any, Literal, Optional

from notebook_intelligence._claude_cli import (
    reject_flag_smuggling,
    run_claude_cli,
    validate_scope,
)
from notebook_intelligence.util import resolve_github_token

log = logging.getLogger(__name__)

PluginScope = Literal["user", "project", "local"]

CLI_TIMEOUT_SECONDS = 60.0
# Marketplace-add fetches the source over the network (git clone, HTTPS
# manifest pull) so it can outlast the default budget on slow links.
CLI_TIMEOUT_MARKETPLACE_ADD_SECONDS = 120.0


_GITHUB_URL_SCHEMES = ("http://", "https://", "git://", "ssh://")
_GITHUB_PREFIX_SCHEMES = ("github:", "git@github.com:")
_ALLOWED_NON_GITHUB_SCHEMES = ("https://",)
_LOCAL_PREFIXES = (".", "/", "~")

# Substrings the underlying `git`/`claude` produce when auth is missing
# or wrong. Used to upgrade an opaque CLI error into a remediation hint
# pointing the user at GITHUB_TOKEN / `gh auth login`.
_AUTH_FAILURE_MARKERS = (
    "authentication failed",
    "could not read username",
    "could not read password",
    "permission denied",
    "401",
    "403",
)


def _looks_like_auth_failure(err: str) -> bool:
    lower = err.lower()
    return any(marker in lower for marker in _AUTH_FAILURE_MARKERS)


def is_github_marketplace_source(source: str) -> bool:
    """Best-effort detector for sources that resolve via GitHub.

    Matches ``github:owner/repo``, ``https://github.com/...``,
    ``http://github.com/...``, ``git://github.com/...``,
    ``ssh://git@github.com/...``, ``git@github.com:owner/repo``, and bare
    ``owner/repo[.git][/]`` shorthand. Used to gate marketplace-add when
    an admin sets ``allow_github_plugin_import = False``. Leans toward
    detection — false positives are a benign UX gate; false negatives
    bypass the policy.
    """
    s = source.strip()
    if not s:
        return False
    lower = s.lower()
    if lower.startswith(_GITHUB_PREFIX_SCHEMES):
        return True
    # ssh://git@github.com/owner/repo — `hostname` returns "github.com".
    if lower.startswith(_GITHUB_URL_SCHEMES):
        host = (urllib.parse.urlparse(s).hostname or "").lower()
        return host == "github.com" or host.endswith(".github.com")
    # owner/repo shorthand. Tolerate trailing slash and `.git` suffix;
    # reject anything path-like or whitespace-bearing.
    if "/" in s and not s.startswith(_LOCAL_PREFIXES) and not any(c.isspace() for c in s):
        stripped = s.rstrip("/")
        if stripped.endswith(".git"):
            stripped = stripped[: -len(".git")]
        return stripped.count("/") == 1
    return False


def is_acceptable_marketplace_source(source: str) -> bool:
    """Reject ``http://`` URLs and exotic schemes (file://, ftp://, etc.) so
    marketplace-add can't be aimed at internal-network HTTP endpoints or
    used for SSRF-style probes. Accepts: ``https://`` URLs, ``github:``,
    ``git@github.com:``, ``git://github.com/...``, ``ssh://git@github.com/...``,
    bare ``owner/repo`` shorthand, and local filesystem paths.
    """
    s = source.strip()
    if not s:
        return False
    lower = s.lower()
    if lower.startswith(_GITHUB_PREFIX_SCHEMES):
        return True
    if s.startswith(_LOCAL_PREFIXES):
        return True
    if lower.startswith(_ALLOWED_NON_GITHUB_SCHEMES):
        return True
    # git:// and ssh:// are accepted only when the host is GitHub; the
    # detector above already short-circuits the policy gate for these.
    if lower.startswith(("git://", "ssh://")):
        return is_github_marketplace_source(s)
    # Bare scheme-less form (`owner/repo` or `./local/path`).
    if "://" not in s and ":" not in s.split("/", 1)[0]:
        return True
    return False


class PluginManager:
    # Class-level so the lock is shared across all PluginManager instances
    # within this process. Handlers construct a fresh manager per request,
    # so an instance lock would fail to serialize concurrent CLI writes.
    _write_lock = asyncio.Lock()

    def __init__(self, working_dir: Optional[str] = None):
        # `claude plugin {install,marketplace add,…} --scope project` resolves
        # the project against the CLI's cwd, so the working_dir must be the
        # user's Jupyter root, not the server process's cwd.
        self._working_dir = working_dir

    # --- reads ---------------------------------------------------------

    async def list_plugins(self) -> list[dict[str, Any]]:
        out = await self._run_cli(["plugin", "list", "--json"])
        return self._parse_json_array(out, "plugin list")

    async def list_marketplaces(self) -> list[dict[str, Any]]:
        out = await self._run_cli(["plugin", "marketplace", "list", "--json"])
        return self._parse_json_array(out, "plugin marketplace list")

    # --- writes (CLI shell-outs) ---------------------------------------

    async def install_plugin(
        self, *, plugin: str, scope: PluginScope = "user"
    ) -> None:
        validate_scope(scope)
        if not plugin:
            raise ValueError("Missing plugin reference")
        reject_flag_smuggling("plugin", plugin)
        async with self._write_lock:
            await self._run_cli(["plugin", "install", "--scope", scope, plugin])

    async def uninstall_plugin(
        self, *, plugin: str, scope: PluginScope = "user"
    ) -> None:
        validate_scope(scope)
        if not plugin:
            raise ValueError("Missing plugin reference")
        reject_flag_smuggling("plugin", plugin)
        async with self._write_lock:
            # `-y` skips the prune-confirmation prompt that the CLI requires
            # when stdin isn't a TTY (we're explicitly closing stdin).
            await self._run_cli(
                ["plugin", "uninstall", "--scope", scope, "-y", plugin]
            )

    async def set_plugin_enabled(
        self, *, plugin: str, enabled: bool, scope: Optional[PluginScope] = None
    ) -> None:
        if not plugin:
            raise ValueError("Missing plugin reference")
        validate_scope(scope, allow_none=True)
        reject_flag_smuggling("plugin", plugin)
        tail = ["plugin", "enable" if enabled else "disable"]
        if scope is not None:
            tail.extend(["--scope", scope])
        tail.append(plugin)
        async with self._write_lock:
            await self._run_cli(tail)

    async def add_marketplace(
        self,
        *,
        source: str,
        scope: PluginScope = "user",
        allow_github: bool = True,
    ) -> None:
        validate_scope(scope)
        if not source:
            raise ValueError("Missing marketplace source")
        reject_flag_smuggling("source", source)
        if not is_acceptable_marketplace_source(source):
            raise ValueError(
                f"Invalid marketplace source {source!r}: only https://, "
                "git@github.com:, github:, ssh://git@github.com, "
                "git://github.com, owner/repo shorthand, and local paths "
                "are accepted"
            )
        if not allow_github and is_github_marketplace_source(source):
            raise PermissionError(
                "Adding marketplaces from GitHub is disabled by your administrator"
            )
        # Inject a GitHub token when adding a GitHub-source marketplace so
        # private repos and corporate-managed GitHub work without asking
        # the user to set process-level env. Resolution chain matches the
        # Skills GitHub-import flow: GITHUB_TOKEN → GH_TOKEN → `gh auth
        # token`. The token never lands in argv (env-only), so DEBUG logs
        # don't leak it.
        env_overrides: Optional[dict[str, str]] = None
        is_github = is_github_marketplace_source(source)
        if is_github:
            token = resolve_github_token()
            if token:
                env_overrides = {"GITHUB_TOKEN": token, "GH_TOKEN": token}
        async with self._write_lock:
            try:
                await self._run_cli(
                    ["plugin", "marketplace", "add", "--scope", scope, source],
                    timeout=CLI_TIMEOUT_MARKETPLACE_ADD_SECONDS,
                    env_overrides=env_overrides,
                )
            except ValueError as exc:
                # Claude/git's auth-failure messages are opaque to a
                # browser user. When we know the source is GitHub and we
                # didn't have a token to inject, prepend a remediation
                # hint so the panel error tells them what to fix.
                if is_github and env_overrides is None and _looks_like_auth_failure(str(exc)):
                    raise ValueError(
                        f"{exc}\n\nNo GitHub token was available — set "
                        "GITHUB_TOKEN or run `gh auth login` on the "
                        "Jupyter server, then retry."
                    ) from exc
                raise

    async def remove_marketplace(self, *, name: str) -> None:
        if not name:
            raise ValueError("Missing marketplace name")
        reject_flag_smuggling("name", name)
        async with self._write_lock:
            await self._run_cli(["plugin", "marketplace", "remove", name])

    # --- internals -----------------------------------------------------

    # Keys we'll walk to find an array of objects when the CLI returns a
    # wrapper shape. Tolerates the documented `{"installed": [...]}` form
    # and the obvious near-future variants without being too greedy —
    # `data` was deliberately excluded because it's generic enough to
    # match wrong shapes (e.g. metadata envelopes).
    _LIST_WRAPPER_KEYS = ("installed", "plugins", "marketplaces", "items")

    @staticmethod
    def _parse_json_array(out: str, what: str) -> list[dict[str, Any]]:
        text = out.strip()
        if not text:
            return []
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not parse {what} JSON output: {exc}") from exc
        if isinstance(doc, list):
            return [d for d in doc if isinstance(d, dict)]
        if isinstance(doc, dict):
            for key in PluginManager._LIST_WRAPPER_KEYS:
                value = doc.get(key)
                if isinstance(value, list):
                    return [d for d in value if isinstance(d, dict)]
        # The CLI returned a non-empty doc we couldn't recognize. Surfacing
        # an error beats returning `[]` and rendering "no plugins installed"
        # — that would silently mask a CLI version skew.
        raise ValueError(
            f"Unrecognized JSON shape from {what}; the Claude CLI may have rev'd"
        )

    async def _run_cli(
        self,
        tail: list[str],
        *,
        timeout: float = CLI_TIMEOUT_SECONDS,
        env_overrides: Optional[dict[str, str]] = None,
    ) -> str:
        return await run_claude_cli(
            tail,
            timeout=timeout,
            label="claude plugin",
            cwd=self._working_dir,
            env_overrides=env_overrides,
        )
