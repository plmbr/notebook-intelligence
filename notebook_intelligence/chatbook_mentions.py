# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Filesystem mentions for natural-language Chatbook cells."""

from __future__ import annotations

import logging
import re
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from notebook_intelligence.api import (
    ChatbookMentionBreadcrumb,
    ChatbookMentionItem,
    ChatbookMentionList,
    ChatbookMentionListRequest,
    ChatbookMentionResolveRequest,
)
from notebook_intelligence.util import (
    get_jupyter_root_dir,
    has_dangerous_text_codepoints,
    is_protected_nbi_path,
    safe_jupyter_path,
)

log = logging.getLogger(__name__)

FILES_ROOT = "builtin:files"
EXTENSION_ROOT_PREFIX = "ext:"
DEFAULT_LIMIT = 100
MAX_FILE_CHARS = 16_000
MAX_PROVIDER_CONTEXT_CHARS = 16_000
MAX_DIRECTORY_ITEMS = 100
BUILTIN_SKIPPED_DIRECTORIES = frozenset({"__pycache__", "node_modules"})

# A mention is either quoted, `@file:"data/my notes.md"`, which is how a path
# containing whitespace or `@` is written, or unquoted and runs to the next
# whitespace. The quoted form follows Claude Code (`@"path"`) and Codex, which
# quotes a picked path containing whitespace. NUI's mention parser
# (plmbr/nui internal/mentions) is meant to accept the same tokens (#503), so
# change the two together.
MENTION_TOKEN_RE = re.compile(
    r'(?<![\w@])@(?:(file|dir|ext):"([^"\n\r\x85\u2028\u2029]+)"(?![\w"])|([^\s@]+))'
)
# Sentence punctuation typed after an unquoted file or dir mention
# (`see @file:notes.md,`) is not part of the path. This follows Claude Code,
# but only for sentence punctuation: `+` or `-` stay part of the name. The
# characters are removed one at a time, at most a few, stopping at the first
# candidate that exists, so a name that really ends in one of them still
# resolves and a shorter, unrelated name is never reached past it.
TRAILING_PUNCTUATION = frozenset(
    ".,;:!?)]}'\"\u2026\u201d\u2019\u00bb"
    "\u3002\u3001\uff0c\uff1b\uff1a\uff01\uff1f\uff09\u300d\u300f"
)
MAX_TRAILING_PUNCTUATION = 5


def _root_path() -> Path:
    root = get_jupyter_root_dir()
    if not root:
        raise RuntimeError("Jupyter root directory is not set")
    return Path(root).expanduser().resolve()


def _relative_display(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _safe_relative_path(
    value: str, skipped_directories: Iterable[str] = ()
) -> Path:
    parts = Path(value).parts
    skipped = set(BUILTIN_SKIPPED_DIRECTORIES)
    skipped.update(str(name) for name in skipped_directories if str(name))
    if (
        not value
        or Path(value).is_absolute()
        or has_dangerous_text_codepoints(value)
        or any(part.startswith(".") for part in parts)
        or any(part in skipped for part in parts)
    ):
        raise ValueError("unsafe mention path")
    path = safe_jupyter_path(value)
    # A workspace symlink can lead to NBI's own config, which the dot-directory
    # check above does not see once the link is resolved.
    if is_protected_nbi_path(path):
        raise ValueError("unsafe mention path")
    return path


def list_filesystem_mentions(
    parent: str = "",
    query: str = "",
    limit: int = DEFAULT_LIMIT,
    skipped_directories: Iterable[str] = (),
) -> dict:
    """List the Files root or bounded workspace file/directory mention items."""
    if not parent:
        return {
            "items": [
                {
                    "label": "Files & folders",
                    "value": FILES_ROOT,
                    "kind": "root",
                    "hasChildren": True,
                }
            ],
            "breadcrumbs": [],
        }
    if parent != FILES_ROOT:
        return {"items": [], "breadcrumbs": []}

    root = _root_path()
    search = query.strip().lower()
    cap = max(1, min(int(limit or DEFAULT_LIMIT), DEFAULT_LIMIT))
    skipped = set(BUILTIN_SKIPPED_DIRECTORIES)
    skipped.update(str(name) for name in skipped_directories if str(name))
    queue: deque[Path] = deque([root])
    found: list[tuple[bool, str, dict]] = []

    while queue and len(found) < cap:
        directory = queue.popleft()
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda path: (not path.is_dir(), path.name.lower()),
            )
        except OSError:
            continue
        for path in entries:
            name = path.name
            if (
                name.startswith(".")
                or path.is_symlink()
                or has_dangerous_text_codepoints(name)
            ):
                continue
            try:
                is_dir = path.is_dir()
            except OSError:
                continue
            if is_dir and name in skipped:
                continue
            try:
                relative = _relative_display(path, root)
            except ValueError:
                continue
            if is_dir:
                queue.append(path)
            if search and search not in name.lower() and search not in relative.lower():
                continue
            kind = "dir" if is_dir else "file"
            label = f"{relative}/" if is_dir else relative
            found.append(
                (
                    is_dir,
                    relative.lower(),
                    {
                        "label": label,
                        "value": f"{kind}:{relative}",
                        "kind": kind,
                        "hasChildren": False,
                    },
                )
            )
            if len(found) >= cap:
                break

    found.sort(key=lambda item: (not item[0], item[1]))
    return {
        "items": [item[2] for item in found[:cap]],
        "breadcrumbs": [{"label": "Files & folders", "value": FILES_ROOT}],
    }


def list_chatbook_mentions(
    parent: str = "",
    query: str = "",
    limit: int = DEFAULT_LIMIT,
    skipped_directories: Iterable[str] = (),
    providers: Iterable[Any] = (),
    notebook_path: str = "",
) -> dict:
    """List built-in and extension-provided Chatbook mentions."""
    provider_list = list(providers)
    if not parent:
        response = list_filesystem_mentions()
        items = list(response["items"])
        for provider in provider_list:
            items.append(
                {
                    "label": str(provider.name or provider.id),
                    "value": _provider_root(provider.id),
                    "kind": "root",
                    "hasChildren": True,
                    "description": str(provider.description or ""),
                }
            )
        items.sort(key=lambda item: str(item.get("label") or "").lower())
        return {"items": items[:_normalize_limit(limit)], "breadcrumbs": []}
    if parent == FILES_ROOT:
        return list_filesystem_mentions(
            parent=parent,
            query=query,
            limit=limit,
            skipped_directories=skipped_directories,
        )

    provider_id, provider_parent = _parse_provider_value(parent)
    provider = next(
        (item for item in provider_list if item.id == provider_id), None
    )
    if provider is None:
        return {"items": [], "breadcrumbs": []}
    request = ChatbookMentionListRequest(
        parent=provider_parent,
        query=query,
        limit=_normalize_limit(limit),
        notebook_path=notebook_path,
        working_directory=get_jupyter_root_dir() or "",
    )
    try:
        result = provider.list_mentions(request)
    except Exception as exc:
        log.warning(
            "Chatbook mention provider '%s' failed to list mentions: %s",
            provider_id,
            exc,
        )
        return {
            "items": [],
            "breadcrumbs": [
                {
                    "label": str(provider.name or provider.id),
                    "value": _provider_root(provider.id),
                }
            ],
        }
    return _format_provider_list(
        provider_id, provider.name, result, limit=request.limit
    )


def _parse_mention_tokens(prompt: str) -> list[tuple[str, str, bool, str]]:
    """Return (kind, value, quoted, token as written), once each, in order."""
    result: list[tuple[str, str, bool, str]] = []
    seen: set[tuple[str, str, bool]] = set()
    for match in MENTION_TOKEN_RE.finditer(prompt or ""):
        if match.group(1):
            kind, value, quoted = match.group(1), match.group(2), True
        else:
            raw = match.group(3)
            kind, separator, value = raw.partition(":")
            if kind not in ("file", "dir", "ext") or not separator:
                continue
            quoted = False
        if (kind, value, quoted) not in seen:
            seen.add((kind, value, quoted))
            result.append((kind, value, quoted, match.group(0)))
    return result


def _path_candidates(value: str, quoted: bool) -> list[str]:
    """The path as written, then with trailing punctuation removed one by one."""
    candidates = [value]
    if quoted:
        return candidates
    while (
        len(candidates) <= MAX_TRAILING_PUNCTUATION
        and len(candidates[-1]) > 1
        and candidates[-1][-1] in TRAILING_PUNCTUATION
    ):
        candidates.append(candidates[-1][:-1])
    return candidates


def _locate_mention_path(
    kind: str,
    value: str,
    quoted: bool,
    root: Path,
    skipped_directories: Iterable[str],
) -> tuple[Path | None, tuple[str, str]]:
    """Find the path a file or dir mention names, and the key to dedupe it on.

    Returns the first candidate that exists, even if it later cannot be read.
    A refused candidate ends the search, so trimming never steps past it.
    """
    candidates = _path_candidates(value, quoted)
    for candidate in candidates:
        try:
            path = _safe_relative_path(candidate, skipped_directories)
            if path.exists():
                return path, (kind, _relative_display(path, root))
        except (OSError, RuntimeError, UnicodeError, ValueError):
            return None, (kind, candidate)
    return None, (kind, candidates[-1])


def parse_chatbook_mentions(prompt: str) -> list[tuple[str, str]]:
    """Return (kind, value as written) for each mention, in prompt order.

    A value is not yet a path: trailing punctuation is trimmed only when the
    mention is resolved. The same text written quoted and unquoted appears
    twice, because the two can resolve differently.
    """
    return [(kind, value) for kind, value, _, _ in _parse_mention_tokens(prompt)]


def resolve_chatbook_mentions(
    prompt: str,
    skipped_directories: Iterable[str] = (),
    providers: Iterable[Any] = (),
    notebook_path: str = "",
    notebook_context: dict | None = None,
    cell_id: str = "",
    prompt_hash: str = "",
    context_hash: str = "",
) -> list[dict[str, str]]:
    """Resolve mention tokens into bounded, soft-failing reference context."""
    mentions = _parse_mention_tokens(prompt)
    if not mentions:
        return []
    root = _root_path()
    provider_by_id = {provider.id: provider for provider in providers}
    current = (notebook_context or {}).get("current") or {}
    cell_index = current.get("index") if isinstance(current, dict) else None
    resolved: list[dict[str, str]] = []
    resolved_keys: set[tuple[str, str]] = set()
    for kind, relative, quoted, token in mentions:
        if kind == "ext":
            # Quoted and unquoted spellings name the same provider value.
            if ("ext", relative) in resolved_keys:
                continue
            resolved_keys.add(("ext", relative))
            provider_id, value = _split_extension_mention(relative)
            provider = provider_by_id.get(provider_id)
            try:
                if provider is None or not value:
                    raise ValueError("unknown mention provider")
                content = provider.resolve_mention(
                    ChatbookMentionResolveRequest(
                        value=value,
                        prompt=prompt,
                        notebook_path=notebook_path,
                        notebook_context=notebook_context,
                        cell_id=cell_id,
                        cell_index=cell_index,
                        prompt_hash=prompt_hash,
                        context_hash=context_hash,
                        working_directory=str(root),
                    )
                )
                content = _truncate_reference(
                    str(content or ""), MAX_PROVIDER_CONTEXT_CHARS
                )
                resolved.append(
                    {
                        "token": token,
                        "kind": "extension",
                        "provider": provider_id,
                        "path": value,
                        "content": content,
                        "available": "true",
                    }
                )
            except Exception:
                resolved.append(
                    {
                        "token": token,
                        "kind": "extension",
                        "provider": provider_id,
                        "path": value,
                        "content": "[unavailable]",
                        "available": "false",
                    }
                )
            continue
        path, key = _locate_mention_path(
            kind, relative, quoted, root, skipped_directories
        )
        if key in resolved_keys:
            continue
        resolved_keys.add(key)
        entry = {
            "token": token,
            "kind": kind,
            "path": key[1] if path is not None else relative,
            "content": "[unavailable]",
            "available": "false",
        }
        if path is not None:
            try:
                if kind == "file":
                    content = _read_text_file(path)
                else:
                    content = _list_directory(path)
                entry.update(content=content, available="true")
            except (OSError, RuntimeError, UnicodeError, ValueError):
                pass
        resolved.append(entry)
    return resolved


def _provider_root(provider_id: str) -> str:
    return f"{EXTENSION_ROOT_PREFIX}{provider_id}"


def _parse_provider_value(value: str) -> tuple[str, str]:
    if not value.startswith(EXTENSION_ROOT_PREFIX):
        return "", ""
    return _split_extension_mention(value.removeprefix(EXTENSION_ROOT_PREFIX))


def _split_extension_mention(value: str) -> tuple[str, str]:
    provider_id, separator, provider_value = value.partition(":")
    return provider_id, provider_value if separator else ""


def _normalize_limit(limit: int) -> int:
    return max(1, min(int(limit or DEFAULT_LIMIT), DEFAULT_LIMIT))


def _format_provider_list(
    provider_id: str,
    provider_name: str,
    result: ChatbookMentionList | dict,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    if isinstance(result, dict):
        raw_items = result.get("items") or []
        raw_breadcrumbs = result.get("breadcrumbs") or result.get("breadcrumb") or []
    else:
        raw_items = result.items or []
        raw_breadcrumbs = result.breadcrumbs or []

    items = []
    for raw in raw_items:
        item = raw if isinstance(raw, ChatbookMentionItem) else ChatbookMentionItem(
            label=str(raw.get("label") or ""),
            value=str(raw.get("value") or ""),
            has_children=bool(raw.get("hasChildren", raw.get("has_children", False))),
            kind=str(raw.get("kind") or "reference"),
            description=str(raw.get("description") or ""),
        )
        value = str(item.value or "")
        prefix = _provider_root(provider_id)
        if value and not value.startswith(prefix + ":"):
            value = f"{prefix}:{value}"
        items.append(
            {
                "label": item.label,
                "value": value,
                "kind": item.kind,
                "hasChildren": item.has_children,
                "description": item.description,
            }
        )

    breadcrumbs = [
        {"label": str(provider_name or provider_id), "value": _provider_root(provider_id)}
    ]
    for raw in raw_breadcrumbs:
        crumb = (
            raw
            if isinstance(raw, ChatbookMentionBreadcrumb)
            else ChatbookMentionBreadcrumb(
                label=str(raw.get("label") or ""),
                value=str(raw.get("value") or raw.get("parent") or ""),
            )
        )
        value = crumb.value
        prefix = _provider_root(provider_id)
        if value and not value.startswith(prefix):
            value = f"{prefix}:{value}"
        breadcrumbs.append({"label": crumb.label, "value": value})
    return {
        "items": items[:_normalize_limit(limit)],
        "breadcrumbs": breadcrumbs,
    }


def _truncate_reference(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def _read_text_file(path: Path) -> str:
    if not path.is_file():
        raise ValueError("not a file")
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ValueError("binary file")
    text = raw.decode("utf-8")
    if len(text) > MAX_FILE_CHARS:
        return text[:MAX_FILE_CHARS] + "\n...[truncated]"
    return text


def _list_directory(path: Path) -> str:
    if not path.is_dir():
        raise ValueError("not a directory")
    entries = []
    for child in sorted(
        path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
    ):
        if child.name.startswith(".") or has_dangerous_text_codepoints(child.name):
            continue
        suffix = "/" if child.is_dir() else ""
        entries.append(child.name + suffix)
        if len(entries) >= MAX_DIRECTORY_ITEMS:
            entries.append("...[truncated]")
            break
    return "\n".join(entries) if entries else "(empty directory)"
