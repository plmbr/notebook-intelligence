# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Admin-supplied tour copy overrides.

A deployment can ship a small YAML (or JSON) file that overlays the
built-in first-run tour copy: per-step titles and descriptions, the
launcher-tile templates, and the overlay's button labels. The path is
configured via the ``NBI_TOUR_CONFIG_PATH`` env var or the
``NotebookIntelligence.tour_config_path`` traitlet.

Hard rules:

- The file ONLY overrides existing fields. Adding new steps or
  reordering them is intentionally not supported: a new step needs a
  DOM anchor and capability gating, which only code can supply.
- The validator fails CLOSED: any unreadable file, parse error, size
  overflow, or schema violation logs a warning and returns ``{}``. The
  sidebar always renders with at least the built-in defaults.
- Per-field length caps prevent a runaway file from blowing out the
  tooltip layout. The frontend re-caps defensively.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger(__name__)

# Hard cap on the file's on-disk size. 32 KB is well over a typical
# customization (a few hundred bytes per overridden step) and well
# under any HTTP-response concern.
MAX_TOUR_CONFIG_BYTES = 32 * 1024

# Per-field length caps. Defense against an admin file with a 10 KB
# description that would push the tooltip off-screen.
MAX_TITLE_CHARS = 80
MAX_DESCRIPTION_CHARS = 400
MAX_BUTTON_LABEL_CHARS = 24
MAX_COMMAND_LABEL_CHARS = 40

# Step ids that admins are allowed to override. Anything else is a
# typo (warn + drop). Kept in sync with ALL_TOUR_STEPS on the
# frontend; if a step is added there, append its id here.
_VALID_STEP_IDS = frozenset(
    {
        "welcome",
        "new-chat",
        "claude-history",
        "settings-gear",
        "slash-commands",
        "add-context",
        "upload-file",
        "drag-and-drop",
        "chat-mode",
        "launcher-tiles",
        "done",
    }
)

# Keys accepted on a per-step override dict. The launcher-tiles step
# additionally accepts the two template fields; everywhere else those
# are flagged as unknown.
_BASE_STEP_KEYS = frozenset({"title", "description", "enabled"})
_LAUNCHER_TILE_TEMPLATE_KEYS = frozenset(
    {"description_singular", "description_plural"}
)

# Top-level sections; anything else is an unknown-key warning.
_TOP_LEVEL_KEYS = frozenset({"steps", "ui", "command"})

# UI button labels the admin can rewrite.
_UI_LABEL_KEYS = frozenset({"skip", "next", "back", "done"})

# Command-palette fields the admin can rewrite.
_COMMAND_KEYS = frozenset({"label"})


class _ValidationContext:
    """Accumulates ``logger.warning`` lines as the loader walks the
    file, then dedupes and emits at the end. Without this, a typo in a
    deployment config would produce N nearly-identical lines per
    capabilities call, which is its own form of log spam."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def flush(self, path: str) -> None:
        # Dedup while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for w in self.warnings:
            if w not in seen:
                unique.append(w)
                seen.add(w)
        if unique:
            joined = "; ".join(unique)
            log.warning(
                "Tour config at %s: %d issue(s) ignored: %s",
                path,
                len(unique),
                joined,
            )


def _truncate(
    value: str, limit: int, ctx: _ValidationContext, field: str
) -> str:
    if len(value) <= limit:
        return value
    ctx.warn(f"{field} truncated from {len(value)} to {limit} chars")
    return value[:limit]


def _validate_step(
    step_id: str, raw: Any, ctx: _ValidationContext
) -> dict[str, Any]:
    """Validate one step's override dict; return the cleaned subset."""
    if not isinstance(raw, dict):
        ctx.warn(f"steps.{step_id} must be a mapping; ignored")
        return {}

    allowed = _BASE_STEP_KEYS
    if step_id == "launcher-tiles":
        # launcher-tiles uses runtime templates; a plain `description`
        # would be dropped on the frontend, so reject it loudly here
        # rather than have it silently no-op.
        allowed = (allowed - {"description"}) | _LAUNCHER_TILE_TEMPLATE_KEYS

    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in allowed:
            ctx.warn(f"steps.{step_id}.{key} is not a recognized field")
            continue
        if key == "enabled":
            if not isinstance(value, bool):
                ctx.warn(
                    f"steps.{step_id}.enabled must be true/false; ignored"
                )
                continue
            cleaned["enabled"] = value
        elif key == "title":
            if not isinstance(value, str):
                ctx.warn(f"steps.{step_id}.title must be a string; ignored")
                continue
            if not value:
                # Empty title would leave the dialog with no accessible
                # name. Treat as no-override rather than wiping the
                # default copy.
                ctx.warn(f"steps.{step_id}.title is empty; ignored")
                continue
            cleaned["title"] = _truncate(
                value, MAX_TITLE_CHARS, ctx, f"steps.{step_id}.title"
            )
        elif key in ("description", "description_singular", "description_plural"):
            if not isinstance(value, str):
                ctx.warn(f"steps.{step_id}.{key} must be a string; ignored")
                continue
            if not value:
                ctx.warn(f"steps.{step_id}.{key} is empty; ignored")
                continue
            cleaned[key] = _truncate(
                value, MAX_DESCRIPTION_CHARS, ctx, f"steps.{step_id}.{key}"
            )
    return cleaned


def _validate_string_section(
    section: str,
    raw: Any,
    allowed_keys: frozenset[str],
    char_cap: int,
    ctx: _ValidationContext,
    unknown_key_msg: str = "is not a recognized field",
) -> dict[str, str]:
    """Generic loop for flat string-mapping admin sections (ui, command).

    Both reject non-mappings, drop unknown keys, drop non-string values,
    drop empty strings, and truncate to a per-section length cap.
    """
    if not isinstance(raw, dict):
        ctx.warn(f"{section} must be a mapping; ignored")
        return {}
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        if key not in allowed_keys:
            ctx.warn(f"{section}.{key} {unknown_key_msg}")
            continue
        if not isinstance(value, str):
            ctx.warn(f"{section}.{key} must be a string; ignored")
            continue
        if not value:
            ctx.warn(f"{section}.{key} is empty; ignored")
            continue
        cleaned[key] = _truncate(value, char_cap, ctx, f"{section}.{key}")
    return cleaned


def _validate_ui(raw: Any, ctx: _ValidationContext) -> dict[str, str]:
    return _validate_string_section(
        "ui",
        raw,
        _UI_LABEL_KEYS,
        MAX_BUTTON_LABEL_CHARS,
        ctx,
        unknown_key_msg="is not a recognized button label",
    )


def _validate_command(raw: Any, ctx: _ValidationContext) -> dict[str, str]:
    return _validate_string_section(
        "command", raw, _COMMAND_KEYS, MAX_COMMAND_LABEL_CHARS, ctx
    )


def _parse(path: str, raw_bytes: bytes) -> Optional[dict[str, Any]]:
    """Decode the file body. YAML is the primary format; JSON parses as
    a strict subset so we try YAML first when available, falling back to
    plain JSON.parse otherwise. Returns ``None`` on parse failure."""
    text = raw_bytes.decode("utf-8", errors="replace")
    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(text)
    except ImportError:
        # PyYAML is a hard dep of jupyter_server, so this branch is
        # essentially unreachable in production; fall back to JSON for
        # weird stripped-down environments anyway.
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("Tour config at %s: JSON parse failed: %s", path, exc)
            return None
    except Exception as exc:
        # yaml.YAMLError + anything obscure (e.g. recursion). Catch
        # broadly so a malformed admin file can never crash the
        # capabilities request.
        log.warning("Tour config at %s: YAML parse failed: %s", path, exc)
        return None

    if parsed is None:
        # Empty file is treated as "no overrides", silently.
        return {}
    if not isinstance(parsed, dict):
        log.warning(
            "Tour config at %s: top-level value must be a mapping; ignored",
            path,
        )
        return None
    return parsed


def load_tour_config(path: Optional[str]) -> dict[str, Any]:
    """Read and validate the admin tour-overrides file.

    Returns the cleaned override dict, ready to ship to the frontend.
    Returns ``{}`` on missing path, missing file, size overflow, parse
    error, or top-level shape violation. Per-field validation issues
    are logged at WARN and the offending fields are dropped while the
    rest of the file is kept.
    """
    if not path:
        return {}

    if not os.path.isfile(path):
        # Silent: a missing file is the steady state for the vast
        # majority of deployments and we don't want to spam logs on
        # every capabilities call.
        return {}

    try:
        size = os.path.getsize(path)
    except OSError as exc:
        log.warning("Tour config at %s: stat failed: %s", path, exc)
        return {}

    if size > MAX_TOUR_CONFIG_BYTES:
        log.warning(
            "Tour config at %s: file size %d exceeds %d-byte cap; ignored",
            path,
            size,
            MAX_TOUR_CONFIG_BYTES,
        )
        return {}

    try:
        with open(path, "rb") as fh:
            raw_bytes = fh.read()
    except OSError as exc:
        log.warning("Tour config at %s: read failed: %s", path, exc)
        return {}

    parsed = _parse(path, raw_bytes)
    if parsed is None:
        return {}

    ctx = _ValidationContext()
    cleaned: dict[str, Any] = {}

    # Top-level sections.
    for key, value in parsed.items():
        if key not in _TOP_LEVEL_KEYS:
            ctx.warn(f"{key} is not a recognized top-level key")
            continue

        if key == "steps":
            if not isinstance(value, dict):
                ctx.warn("steps must be a mapping; ignored")
                continue
            steps_cleaned: dict[str, dict[str, Any]] = {}
            for step_id, step_raw in value.items():
                if step_id not in _VALID_STEP_IDS:
                    ctx.warn(f"steps.{step_id} is not a known step id")
                    continue
                step_cleaned = _validate_step(step_id, step_raw, ctx)
                if step_cleaned:
                    steps_cleaned[step_id] = step_cleaned
            if steps_cleaned:
                cleaned["steps"] = steps_cleaned

        elif key == "ui":
            ui_cleaned = _validate_ui(value, ctx)
            if ui_cleaned:
                cleaned["ui"] = ui_cleaned

        elif key == "command":
            command_cleaned = _validate_command(value, ctx)
            if command_cleaned:
                cleaned["command"] = command_cleaned

    ctx.flush(path)
    return cleaned
