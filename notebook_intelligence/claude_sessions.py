# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Discovery of Claude Code session transcripts.

Claude Code persists each conversation as a line-delimited JSON file at::

    <claude-config-dir>/projects/<cwd-encoded>/<session-id>.jsonl

where ``<claude-config-dir>`` is ``~/.claude`` unless the CLI's
``CLAUDE_CONFIG_DIR`` env var overrides it, and ``<cwd-encoded>`` is the
session cwd with path separators replaced by dashes (e.g.
``/Users/me/proj`` -> ``-Users-me-proj``).

This module reads those files for the current Jupyter working directory and
returns lightweight metadata (id, timestamps, first user message preview) so
the UI can offer a "resume previous session" picker.

Each line in a transcript is a JSON object. User messages look like::

    {"type": "user", "message": {"role": "user", "content": "..."}, ...}

``content`` can be a string (the common case) or a list of content blocks in
the Anthropic format. Other line types (assistant replies, tool events,
snapshots) are ignored for preview purposes.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from notebook_intelligence.util import get_claude_config_dir

log = logging.getLogger(__name__)

_PREVIEW_MAX_CHARS = 160

# Hard cap on lines scanned per file while looking for the first user
# message. Transcripts can grow very large, and in practice the first user
# prompt is on the first few lines.
_MAX_LINES_SCANNED = 200

# Skip filter shared by the chat-sidebar picker and the launcher tile so
# they can't disagree on what to show for the same session id.
NBI_CONTEXT_PREFIX = "Additional context: Current directory open in Jupyter is:"
# A user prompt that genuinely starts with one of these prefixes (e.g.
# "what does <command-name> do?") would be skipped in favor of the next
# message — acceptable trade-off.
_SKIPPABLE_PREFIXES = (
    NBI_CONTEXT_PREFIX,
    "<local-command-",
    "<command-",
    "[Request interrupted by user",
    "Unknown slash command:",
    "Unknown skill:",
)
# Control-only slash commands the user typed to manage the session itself
# rather than ask Claude something. A regex like ^/[A-Za-z]+$ would also
# match "/tmp" or "/etc" — common file paths someone might paste — so we
# enumerate the known set instead. Public because claude.py also consults
# it when assembling the CLI query: attachment context is meaningless to
# these commands, but must be preserved for every other command.
CONTROL_SLASH_COMMANDS = frozenset({
    "/clear",
    "/compact",
    "/context",
    "/cost",
    "/exit",
    "/help",
    "/init",
    "/login",
    "/logout",
    "/quit",
    "/release-notes",
    "/reset",
    "/status",
})
_CONTROL_SLASH_COMMANDS = CONTROL_SLASH_COMMANDS


@dataclass
class ClaudeSessionInfo:
    """Lightweight metadata for a Claude Code session transcript."""

    session_id: str
    path: str
    modified_at: float
    created_at: float
    preview: str
    cwd: str = ""


def encode_cwd(cwd: str) -> str:
    """Encode a filesystem path the way Claude Code names its project dirs.

    Claude Code replaces every path separator with a dash, so
    ``/Users/me/proj`` becomes ``-Users-me-proj``. We resolve symlinks
    first to match Claude Code's own behavior — without this, macOS's
    ``/tmp`` (a symlink to ``/private/tmp``) would map to ``-tmp`` here
    while Claude Code stores transcripts under ``-private-tmp``, so the
    picker would silently find no sessions.
    """
    normalized = os.path.realpath(cwd)
    return normalized.replace(os.sep, "-")


def get_sessions_dir(cwd: str, claude_home: Optional[str] = None) -> Path:
    """Return the directory containing session transcripts for ``cwd``.

    ``claude_home`` defaults to the CLI's own config dir (``CLAUDE_CONFIG_DIR``
    when set, else ``~/.claude``) but can be overridden, mainly for tests.
    """
    home = Path(claude_home) if claude_home else Path(get_claude_config_dir())
    return home / "projects" / encode_cwd(cwd)


def _list_sessions_in_dir(
    cwd: str,
    claude_home: Optional[str] = None,
) -> list[ClaudeSessionInfo]:
    """List Claude sessions for ``cwd``, newest first.

    Returns an empty list if the project directory doesn't exist or contains
    no transcripts. Corrupt or unreadable files are skipped with a log
    warning rather than raising.
    """
    sessions_dir = get_sessions_dir(cwd, claude_home=claude_home)
    if not sessions_dir.is_dir():
        return []

    sessions: list[ClaudeSessionInfo] = []
    for entry in sessions_dir.iterdir():
        # Only consider top-level .jsonl files; skip nested subagent dirs.
        if not entry.is_file() or entry.suffix != ".jsonl":
            continue
        info = _read_session_info(entry)
        if info is not None:
            sessions.append(info)

    sessions.sort(key=lambda s: s.modified_at, reverse=True)
    return sessions


def _read_session_info(path: Path) -> Optional[ClaudeSessionInfo]:
    """Read metadata from a single transcript file.

    Returns a ``ClaudeSessionInfo`` whenever the file contains at least
    one user message, even if every message is skippable — in that case
    ``preview`` is empty and the picker UI relies on the session id +
    timestamp meta row instead of rendering a literal "/exit"-style line
    (issue #187).

    Returns ``None`` for transcripts that aren't useful to resume: the
    file is unreadable, starts with a sidechain record (subagent probe),
    or contains no user messages at all (snapshot-only).

    The ``cwd`` is sourced from the transcript itself (Claude Code writes
    a ``cwd`` field on most message envelopes) rather than reverse-
    engineering from the encoded directory name, which is ambiguous for
    paths that contain literal dashes (e.g. ``/Users/me/get-noticed``).
    """
    try:
        stat = path.stat()
    except OSError as exc:
        log.warning("Could not stat Claude session file %s: %s", path, exc)
        return None

    preview = ""
    saw_user_message = False
    first_parsed_obj = True
    cwd_from_transcript = ""

    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in itertools.islice(fh, _MAX_LINES_SCANNED):
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    # Tolerate the occasional partial write at the tail
                    # of an in-progress session.
                    continue
                # Sidechain transcripts (subagent probes) aren't resumable
                # via `claude --resume`; skip files whose first record is a
                # sidechain.
                if first_parsed_obj:
                    first_parsed_obj = False
                    if obj.get("isSidechain") is True:
                        return None
                # Pick up the cwd as soon as we find a record that
                # carries one. Most lines do; the first that does wins.
                if not cwd_from_transcript:
                    candidate = obj.get("cwd")
                    if isinstance(candidate, str) and candidate:
                        cwd_from_transcript = candidate
                if not _is_user_message(obj):
                    continue
                saw_user_message = True
                if _is_skippable_user_message(obj):
                    continue
                if not preview:
                    preview = _extract_preview(obj)
                # We need both the preview AND the cwd before we can
                # stop. Most envelopes carry cwd, so this loop usually
                # exits within the first few lines; otherwise the
                # _MAX_LINES_SCANNED cap above provides the upper bound.
                if cwd_from_transcript:
                    break
    except OSError as exc:
        log.warning("Could not read Claude session file %s: %s", path, exc)
        return None

    if not saw_user_message:
        # Pure snapshot / non-conversation file — drop, nothing to resume.
        return None

    return ClaudeSessionInfo(
        session_id=path.stem,
        path=str(path),
        modified_at=stat.st_mtime,
        created_at=stat.st_ctime,
        preview=preview,
        cwd=cwd_from_transcript,
    )


def _is_user_message(obj: dict) -> bool:
    if obj.get("type") != "user":
        return False
    message = obj.get("message")
    if not isinstance(message, dict):
        return False
    # Guard against tool-result "user" envelopes; we only want real prompts.
    content = message.get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(
            isinstance(block, dict) and block.get("type") == "text"
            for block in content
        )
    return False


def _is_skippable_user_message(obj: dict) -> bool:
    content = obj.get("message", {}).get("content")
    if isinstance(content, str):
        return _is_skippable_text(content)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                return isinstance(text, str) and _is_skippable_text(text)
    return False


def _strip_nbi_context_preamble(text: str) -> str:
    """Strip the NBI context-preamble line if it leads ``text``.

    The backend appends the preamble (``Additional context: ...``) as
    its own user-role message in ``extension.py``, but ``claude.py``
    joins consecutive user-role entries with ``\\n`` before handing
    them to the SDK. The session transcript therefore records one
    combined user message whose first line is the preamble and whose
    remainder is the user's actual prompt. Returning the remainder
    here lets the skip and preview logic treat the joined form like
    the separate form (issue #329).

    Returns ``text`` unchanged when the preamble isn't present.
    Returns an empty string when the preamble is the entire message
    (no newline, no following content).
    """
    if not text.startswith(NBI_CONTEXT_PREFIX):
        return text
    newline_at = text.find("\n")
    if newline_at == -1:
        return ""
    return text[newline_at + 1 :]


def _is_skippable_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    # Unwrap the NBI preamble before checking the rest of the skip
    # rules: the preamble itself is skippable, but the user's actual
    # prompt that follows it (when claude.py joined the two user-role
    # messages into one) usually isn't. Without this, a single-prompt
    # session shows no preview because the only user message starts
    # with the preamble.
    if stripped.startswith(NBI_CONTEXT_PREFIX):
        # Recurses at most once. NBI_CONTEXT_PREFIX is single-line, so
        # the helper strips through the first newline (or returns ""
        # when no newline exists). The unwrapped tail therefore cannot
        # itself start with the preamble — the recursive call falls
        # through to the legacy prefix / control-command checks or
        # bottoms out on the empty-stripped guard at the top of this
        # function.
        return _is_skippable_text(_strip_nbi_context_preamble(stripped))
    if stripped.startswith(_SKIPPABLE_PREFIXES):
        return True
    return stripped in _CONTROL_SLASH_COMMANDS


def _extract_preview(obj: dict) -> str:
    """Extract a short preview string from a user message line."""
    content = obj.get("message", {}).get("content")
    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        text = "\n".join(parts)

    # Drop the NBI context preamble line if claude.py joined it onto
    # the front of the user's actual prompt (issue #329). Without
    # this, the preview reads "Additional context: ..." instead of
    # what the user asked.
    text = _strip_nbi_context_preamble(text)

    # Collapse whitespace so multi-line prompts render as a single row.
    text = " ".join(text.split())
    return _truncate_preview(text)


def _truncate_preview(text: str) -> str:
    if len(text) > _PREVIEW_MAX_CHARS:
        return text[: _PREVIEW_MAX_CHARS - 1].rstrip() + "\u2026"
    return text


# Module-level cache: (transcript_path, mtime) -> parsed ClaudeSessionInfo.
# Avoids re-reading every .jsonl on every list call (D207). Invalidates
# automatically on mtime change. Capped so a long-running server doesn't
# unbounded-grow; bumping out the oldest entry is fine since the cache
# is purely a performance hint.
_SESSION_INFO_CACHE: "dict[tuple[str, float], Optional[ClaudeSessionInfo]]" = {}
_SESSION_INFO_CACHE_MAX = 2048


def _cached_read_session_info(path: Path) -> Optional[ClaudeSessionInfo]:
    """``_read_session_info`` with mtime-keyed memoization.

    Returns the cached parse when the file hasn't been touched since the
    last call, otherwise re-parses. Treats stat failures the same as the
    underlying function: warn and skip.
    """
    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        log.warning("Could not stat Claude session file %s: %s", path, exc)
        return None
    key = (str(path), mtime)
    cached = _SESSION_INFO_CACHE.get(key)
    if cached is not None or key in _SESSION_INFO_CACHE:
        return cached
    info = _read_session_info(path)
    # Bound the cache size with a simple FIFO eviction; we're not trying
    # to be LRU-clever for a few thousand transcripts.
    if len(_SESSION_INFO_CACHE) >= _SESSION_INFO_CACHE_MAX:
        try:
            oldest = next(iter(_SESSION_INFO_CACHE))
            del _SESSION_INFO_CACHE[oldest]
        except StopIteration:
            pass
    _SESSION_INFO_CACHE[key] = info
    return info


def _decode_cwd_from_dir_name(name: str) -> str:
    """Best-effort cwd recovery from a Claude project-dir name.

    Used only as a fallback when the transcript itself has no ``cwd``
    field. Claude encodes path separators as dashes, so ``-Users-me-proj``
    becomes ``/Users/me/proj``. Paths with literal dashes are ambiguous
    and will mis-decode; the transcript-derived cwd should be preferred
    whenever it's available.
    """
    if not name:
        return ""
    if name.startswith("-"):
        return "/" + name[1:].replace("-", "/")
    return name.replace("-", "/")


def list_all_sessions(
    cwd: Optional[str] = None,
    claude_home: Optional[str] = None,
) -> list[ClaudeSessionInfo]:
    """List every resumable Claude session on disk, newest first.

    Walks ``<claude-config-dir>/projects/*/`` directly so the result is the
    same set of sessions ``claude --resume`` can recover. ``history.jsonl`` is
    NOT used as a gating source because recent Claude Code versions don't
    reliably populate it (notably for SDK-driven invocations), and
    history-first lookups silently dropped real, on-disk sessions.

    The ``cwd`` is taken from the transcript itself when present (Claude
    Code writes it on most message envelopes); falls back to a dash-
    decoded project-dir name when no transcript line carries a cwd.

    The ``cwd`` argument is retained for backward compatibility; when
    given it's only used to scope same-cwd sessions whose project dir
    might not exist yet (e.g. an in-progress NBI Claude Mode session).
    Cross-project enumeration is unconditional.

    Sessions are de-duplicated by session id and sorted by most recent
    activity. Per-transcript parse results are mtime-cached so repeated
    calls don't reparse every file.
    """
    home = Path(claude_home) if claude_home else Path(get_claude_config_dir())
    projects_dir = home / "projects"

    sessions: list[ClaudeSessionInfo] = []
    seen_ids: set[str] = set()

    if projects_dir.is_dir():
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            fallback_cwd = _decode_cwd_from_dir_name(project_dir.name)
            for jsonl_file in project_dir.glob("*.jsonl"):
                info = _cached_read_session_info(jsonl_file)
                if info is None or info.session_id in seen_ids:
                    continue
                # Fall back to the dash-decoded dir name only when the
                # transcript itself didn't yield a cwd.
                if not info.cwd:
                    info.cwd = fallback_cwd
                sessions.append(info)
                seen_ids.add(info.session_id)

    # Belt and suspenders: if the caller asked for sessions scoped to a
    # specific cwd whose project dir doesn't exist yet (e.g. a brand-new
    # NBI Claude Mode session being recorded), surface them too.
    if cwd:
        for s in _list_sessions_in_dir(cwd, claude_home=claude_home):
            if s.session_id in seen_ids:
                continue
            if not s.cwd:
                s.cwd = cwd
            sessions.append(s)
            seen_ids.add(s.session_id)

    sessions.sort(key=lambda s: s.modified_at, reverse=True)
    return sessions
