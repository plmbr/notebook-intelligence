# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Shared helpers for Claude-CLI shell-outs.

Used by `claude_mcp_manager` and `plugin_manager`. Both wrap subsets of the
`claude` CLI; this module owns the invariants:

  * Closed stdin so prompts (project-trust, OAuth) fail fast.
  * Per-call timeout with a clean ``TimeoutError``.
  * Stderr-preferred error message on non-zero exit.
  * Argv redaction for secret-bearing flags before logging.
  * CLI path resolution via ``resolve_claude_cli_path()``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from notebook_intelligence.util import resolve_claude_cli_path

log = logging.getLogger(__name__)

CLI_TIMEOUT_DEFAULT_SECONDS = 60.0

# Both managers store config under the same three Claude scopes — kept
# here so a fourth surface (ACP, hooks, etc.) doesn't redefine the tuple.
CLAUDE_SCOPES: tuple[str, ...] = ("user", "project", "local")


def validate_scope(scope: str, *, allow_none: bool = False) -> None:
    """Raise ``ValueError`` unless ``scope`` is a recognized Claude scope.

    With ``allow_none=True`` the value ``None`` is accepted (callers that
    want to omit the ``--scope`` flag entirely).
    """
    if scope is None and allow_none:
        return
    if scope not in CLAUDE_SCOPES:
        raise ValueError(
            f"Invalid scope {scope!r}; expected one of {CLAUDE_SCOPES}"
        )

# Flags whose value should never appear in logs. Includes the documented
# secret-bearing flags from the claude CLI's `--help` output even where the
# managers don't currently pass them — the cost of a forward-compat entry
# is negligible vs an accidental leak.
_SECRET_BEARING_FLAGS = frozenset(
    [
        "-e",
        "--env",
        "-H",
        "--header",
        "--client-secret",
        "--client-id",
        "--token",
        "--password",
        "--auth",
        "--bearer",
    ]
)


def redact_argv_for_log(argv: list[str]) -> list[str]:
    """Redact the value following any secret-bearing flag for logs."""
    redacted: list[str] = []
    skip_next = False
    for token in argv:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        redacted.append(token)
        if token in _SECRET_BEARING_FLAGS:
            skip_next = True
    return redacted


def reject_flag_smuggling(label: str, value: str) -> None:
    """Reject values starting with ``-`` so user input can't be parsed as a
    CLI flag through its position in argv."""
    if value.startswith("-"):
        raise ValueError(f"Invalid {label} {value!r}: leading '-' is not permitted")


def claude_cli_argv(tail: list[str]) -> list[str]:
    """Build a full argv list with the resolved Claude CLI as argv[0]."""
    cli = resolve_claude_cli_path()
    if not cli:
        raise FileNotFoundError(
            "Claude Code CLI not found on PATH (set NBI_CLAUDE_CLI_PATH or install `claude`)"
        )
    return [cli, *tail]


async def run_claude_cli(
    tail: list[str],
    *,
    cwd: Optional[str] = None,
    timeout: float = CLI_TIMEOUT_DEFAULT_SECONDS,
    label: str = "claude",
    env_overrides: Optional[dict[str, str]] = None,
) -> str:
    """Run ``claude <tail...>`` and return its stdout.

    ``env_overrides`` merges into the parent's environment for this call
    only — used by callers that need to inject auth (e.g., a resolved
    ``GITHUB_TOKEN`` for marketplace fetches against private repos).
    Values pass via env, not argv, so they don't appear in the redacted
    DEBUG log.

    Raises:
        FileNotFoundError: when the CLI can't be resolved.
        TimeoutError: when the call exceeds ``timeout``.
        ValueError: on non-zero exit (carrying the CLI's stderr/stdout).
    """
    argv = claude_cli_argv(tail)
    # Per-invocation log goes to DEBUG: list-style endpoints (`plugin list`,
    # `mcp list`) fire on every panel mount, and operators rarely care about
    # individual successful invocations. Failures still raise a `ValueError`
    # carrying the CLI's own stderr, which callers surface to the user.
    log.debug("%s invocation: %s", label, " ".join(redact_argv_for_log(argv[1:])))
    if env_overrides:
        # Log only the keys, never the values — answers "did my token get
        # used?" without leaking the secret.
        log.debug("%s env injected: %s", label, sorted(env_overrides.keys()))
    env = {**os.environ, **env_overrides} if env_overrides else None
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"`{label}` timed out after {timeout}s")
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raw = (err or out).strip() or f"{label} failed (exit {proc.returncode})"
        # The CLI's stderr is forwarded to the browser via the handlers'
        # `_error()`; scrub any injected secret that the underlying tool
        # might have echoed (git in verbose mode, curl 401 challenges, etc.).
        raise ValueError(_scrub_env_overrides(raw, env_overrides))
    return out


def _scrub_env_overrides(text: str, env_overrides: Optional[dict[str, str]]) -> str:
    """Replace any env_overrides values that appear in `text` with `<redacted>`.

    Defense-in-depth: tokens flow via env (not argv) so they don't reach
    process listings, but a misbehaving downstream tool (git with
    GIT_TRACE=1, a verbose credential helper) can still echo them into
    stderr. The handler surfaces stderr to the browser; this scrub prevents
    the resulting 4xx response body from containing the secret.

    Routes through ``util._replace_values`` so the redaction contract
    (literal-substring match, 8-char value floor, `<redacted>` placeholder)
    stays consistent with the process-env scrub used by the shell tools.
    """
    if not env_overrides:
        return text
    # Local import keeps the util dep behind the call site so a module-load
    # cycle (claude_cli imported during extension setup) can't bite.
    from notebook_intelligence.util import _replace_values
    return _replace_values(text, env_overrides.values())
