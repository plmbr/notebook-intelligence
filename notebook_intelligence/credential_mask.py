# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Keep stored API keys out of the capabilities response.

A key kept in config.json, whether typed in the settings panel or written by
hand, used to travel to the browser in clear text and fill a plain input. The
capabilities handler now sends ``SECRET_MASK`` in its place, and the config
handler maps the mask posted back onto the stored key. The panel can then
re-save its form untouched without overwriting the key it never saw.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable, Optional

from notebook_intelligence.util import _SECRET_ENV_NAME_PATTERNS

SECRET_MASK = "********"

# Property ids treated as credentials even when a provider did not set
# ``secret``, so an extension that names its key ``api_key`` cannot leak it by
# omission.
SECRET_PROPERTY_IDS = frozenset({"api_key"})


def _is_secret_property(prop: dict) -> bool:
    return bool(prop.get("secret")) or prop.get("id") in SECRET_PROPERTY_IDS


def mask_secret(value: Any) -> Any:
    """The mask for a non-empty string; anything else unchanged.

    An empty value stays empty so the panel can tell "no key" from "a key".
    """
    if isinstance(value, str) and value:
        return SECRET_MASK
    return value


def mask_settings_api_key(settings: Optional[dict]) -> Optional[dict]:
    """A copy of a Claude or ACP settings dict with its ``api_key`` masked."""
    if not isinstance(settings, dict) or not settings.get("api_key"):
        return settings
    result = dict(settings)
    result["api_key"] = mask_secret(result["api_key"])
    return result


def restore_masked_api_key(posted: Any, stored: Any) -> Any:
    """Swap a posted mask for the stored ``api_key``.

    ``stored`` without a key yields an empty one: a mask with nothing behind it
    must not be saved as though it were the key.
    """
    if not isinstance(posted, dict) or posted.get("api_key") != SECRET_MASK:
        return posted
    result = dict(posted)
    stored_key = stored.get("api_key", "") if isinstance(stored, dict) else ""
    result["api_key"] = stored_key if isinstance(stored_key, str) else ""
    return result


def mask_model_properties(models: list[dict]) -> list[dict]:
    """Copies of the model dicts with each secret property's value masked.

    The ``secret`` flag is set on what is sent, so the panel renders a
    password field for a property a provider left unflagged.
    """
    masked = []
    for model in models:
        properties = model.get("properties")
        if not isinstance(properties, list):
            masked.append(model)
            continue
        masked.append(
            {
                **model,
                "properties": [
                    {**prop, "value": mask_secret(prop.get("value")), "secret": True}
                    if _is_secret_property(prop)
                    else prop
                    for prop in properties
                ],
            }
        )
    return masked


def mask_model_config(model_config: Any) -> Any:
    """A copy of a stored ``chat_model`` / ``inline_completion_model`` entry
    (``{provider, model, properties: [{id, value}]}``) with secret property
    values masked. The capabilities response carries this entry as well as the
    model list, and both must mask."""
    properties = model_config.get("properties") if isinstance(model_config, dict) else None
    if not isinstance(properties, list):
        return model_config
    return {
        **model_config,
        "properties": [
            {**prop, "value": mask_secret(prop.get("value"))}
            if isinstance(prop, dict) and _is_secret_property(prop)
            else prop
            for prop in properties
        ],
    }


def restore_masked_model_properties(posted: Any, stored: Any) -> Any:
    """Swap posted property masks for the values stored for the same model.

    Only the model the config already names can legitimately hold a key, since
    the server loads property values for the selected model alone. A mask for
    any other model has no key behind it and becomes empty.
    """
    if not isinstance(posted, dict) or not isinstance(posted.get("properties"), list):
        return posted
    same_model = (
        isinstance(stored, dict)
        and stored.get("provider") == posted.get("provider")
        and stored.get("model") == posted.get("model")
    )
    stored_values = {}
    if same_model and isinstance(stored.get("properties"), list):
        stored_values = {
            prop.get("id"): prop.get("value", "")
            for prop in stored["properties"]
            if isinstance(prop, dict)
        }
    properties = []
    for prop in posted["properties"]:
        if isinstance(prop, dict) and prop.get("value") == SECRET_MASK:
            prop = {**prop, "value": stored_values.get(prop.get("id"), "")}
        properties.append(prop)
    return {**posted, "properties": properties}


# MCP server entries carry credentials in two maps: stdio ``env`` and remote
# ``headers``. Names are matched case-insensitively with ``-`` read as ``_``,
# using the shell-output redactor's list plus the bare words an MCP config
# tends to use (``X-Api-Key``, ``MY_KEY``).
_MCP_SECRET_NAME_PATTERNS = (*_SECRET_ENV_NAME_PATTERNS, "KEY", "PASS")
_MCP_CREDENTIAL_FIELDS = ("env", "headers")


def _is_secret_name(name: Any) -> bool:
    upper = str(name).upper().replace("-", "_")
    return any(pattern in upper for pattern in _MCP_SECRET_NAME_PATTERNS)


def _mcp_servers(config: Any) -> dict:
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    return servers if isinstance(servers, dict) else {}


def mask_mcp_server_credentials(server: dict) -> dict:
    """A copy of a Claude MCP server dict with every ``env`` and ``headers``
    value masked. The panel lists names only, so nothing there needs a value."""
    result = dict(server)
    for field in _MCP_CREDENTIAL_FIELDS:
        values = result.get(field)
        if isinstance(values, dict):
            result[field] = {key: mask_secret(value) for key, value in values.items()}
    return result


def mask_mcp_config(config: Any) -> Any:
    """A copy of an ``mcp.json`` document with credential-named ``env`` and
    ``headers`` values masked, for the editor that shows the file.

    Only names that look like credentials are masked, so settings such as
    ``PYTHONPATH`` stay editable. ``args`` and ``url`` are left as they are:
    a secret inside one cannot be told from the rest of the string.
    """
    result = copy.deepcopy(config)
    for server in _mcp_servers(result).values():
        if not isinstance(server, dict):
            continue
        for field in _MCP_CREDENTIAL_FIELDS:
            values = server.get(field)
            if isinstance(values, dict):
                for key, value in values.items():
                    if _is_secret_name(key):
                        values[key] = mask_secret(value)
    return result


def has_masked_mcp_values(config: Any) -> bool:
    """Whether a posted ``mcp.json`` carries any mask to restore."""
    return any(
        isinstance(server, dict)
        and any(
            isinstance(server.get(field), dict)
            and SECRET_MASK in server[field].values()
            for field in _MCP_CREDENTIAL_FIELDS
        )
        for server in _mcp_servers(config).values()
    )


class UnresolvedMaskError(ValueError):
    """A posted mask has no stored value behind it. ``names`` lists each as
    ``server.field.key`` so the handler can word the message in the user's
    language."""

    def __init__(self, names: list):
        super().__init__(
            "Masked MCP values with no saved value: " + ", ".join(names)
        )
        self.names = list(names)


def restore_masked_mcp_config(posted: Any, stored: Any) -> Any:
    """Swap masks in a posted ``mcp.json`` for the stored values.

    Raises ``UnresolvedMaskError`` naming each mask with no stored value
    behind it (a renamed server, or a key added as the mask), so the save is
    refused instead of persisting ``********`` as a credential.
    """
    result = copy.deepcopy(posted)
    stored_servers = _mcp_servers(stored)
    unresolved = []
    for name, server in _mcp_servers(result).items():
        if not isinstance(server, dict):
            continue
        for field in _MCP_CREDENTIAL_FIELDS:
            values = server.get(field)
            if not isinstance(values, dict):
                continue
            stored_values = (stored_servers.get(name) or {}).get(field)
            for key, value in values.items():
                if value != SECRET_MASK:
                    continue
                if isinstance(stored_values, dict) and isinstance(
                    stored_values.get(key), str
                ):
                    values[key] = stored_values[key]
                else:
                    unresolved.append(f"{name}.{field}.{key}")
    if unresolved:
        raise UnresolvedMaskError(unresolved)
    return result


def credential_parts(value: str) -> list:
    """The value, plus the token of a ``Bearer abc`` style header value."""
    parts = [value]
    scheme, _, token = value.partition(" ")
    if token and scheme.isalpha():
        parts.append(token.strip())
    return parts


# What the OpenAI-compatible clients document as the "key" for a server that
# checks none (Ollama, LM Studio, vLLM, llama.cpp). They are not secrets, and
# redacting them would blank ordinary words wherever shell output mentions
# them. Compared lower-cased, with ``_`` read as ``-``.
PLACEHOLDER_API_KEYS = frozenset(
    {
        "dummy",
        "dummy-api-key",
        "dummy-key",
        "empty",
        "fake-key",
        "lm-studio",
        "lmstudio",
        "no-key",
        "no-key-required",
        "no-api-key",
        "none",
        "not-needed",
        "not-required",
        "null",
        "ollama",
        "placeholder",
        "sk-no-key-required",
    }
)


def is_placeholder_api_key(value: str) -> bool:
    return value.strip().lower().replace("_", "-") in PLACEHOLDER_API_KEYS


def collect_stored_secrets(configs: Iterable[Any], mcp: Any) -> list:
    """Every credential value NBI keeps in its config, for output redaction.

    ``configs`` are config.json layers; ``mcp`` is the merged mcp.json.
    """
    found = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value and value != SECRET_MASK:
            parts = credential_parts(value)
            # `Bearer not-needed` is as much a placeholder as `not-needed`.
            if not any(is_placeholder_api_key(part) for part in parts):
                found.extend(parts)

    for config in configs:
        if not isinstance(config, dict):
            continue
        for key in ("claude_settings", "acp_settings"):
            settings = config.get(key)
            if isinstance(settings, dict):
                add(settings.get("api_key"))
        for key in ("chat_model", "inline_completion_model"):
            model = config.get(key)
            properties = model.get("properties") if isinstance(model, dict) else None
            for prop in properties if isinstance(properties, list) else []:
                if isinstance(prop, dict) and prop.get("id") in SECRET_PROPERTY_IDS:
                    add(prop.get("value"))
    for server in _mcp_servers(mcp).values():
        if not isinstance(server, dict):
            continue
        for field in _MCP_CREDENTIAL_FIELDS:
            values = server.get(field)
            if isinstance(values, dict):
                for key, value in values.items():
                    if _is_secret_name(key):
                        add(value)
    return found
