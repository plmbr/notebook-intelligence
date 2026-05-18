# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Pin the contract that shell-tool output is scrubbed of process-env
secrets before it reaches chat history. A verbose command like `env` or
a misbehaving binary that dumps env on error would otherwise surface
the user's own GITHUB_TOKEN, ANTHROPIC_API_KEY, etc. into the chat
transcript (and through to the LLM provider, audit log, and client
tabs)."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from notebook_intelligence import built_in_toolsets as toolsets
from notebook_intelligence.util import redact_env_secrets, set_jupyter_root_dir


class TestRedactProcessSecrets:
    def test_redacts_value_with_sensitive_name(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_supersecret1234")
        text = "fatal: could not authenticate with token ghp_supersecret1234"
        out = redact_env_secrets(text)
        assert "ghp_supersecret1234" not in out
        assert "<redacted>" in out

    def test_redacts_multiple_secret_names(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_aaaaaaaa")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-bbbbbbbb")
        monkeypatch.setenv("MY_PASSWORD", "p@ssw0rd1234")
        text = (
            "GITHUB_TOKEN=ghp_aaaaaaaa "
            "ANTHROPIC_API_KEY=sk-ant-bbbbbbbb "
            "MY_PASSWORD=p@ssw0rd1234"
        )
        out = redact_env_secrets(text)
        assert "ghp_aaaaaaaa" not in out
        assert "sk-ant-bbbbbbbb" not in out
        assert "p@ssw0rd1234" not in out

    def test_ignores_non_sensitive_names(self, monkeypatch):
        # PATH, HOME, USER, etc. should not have their values redacted.
        # The redactor's purpose is to scrub secrets, not to mask all env.
        monkeypatch.setenv("MY_HARMLESS_VAR", "harmless_value_long_enough")
        text = "MY_HARMLESS_VAR=harmless_value_long_enough"
        out = redact_env_secrets(text)
        assert "harmless_value_long_enough" in out
        assert "<redacted>" not in out

    def test_skips_short_values(self, monkeypatch):
        # A 4-char TOKEN value would generate too many false positives if
        # redacted (might match incidental short strings in command output).
        # The length floor avoids that.
        monkeypatch.setenv("DEV_TOKEN", "abc")
        text = "abc is short and incidental"
        out = redact_env_secrets(text)
        assert out == text

    def test_redacts_token_substring_match(self, monkeypatch):
        # Name patterns are substring, so `GH_TOKEN`, `MY_AUTH_TOKEN`,
        # `SOME_API_KEY`, `NEW_SECRET_VALUE`, etc. all match. Pin this
        # because a future refactor that switches to exact-match would
        # silently miss most real-world secret env vars.
        for name in ("GH_TOKEN", "MY_AUTH_TOKEN", "SOME_API_KEY", "MY_PASSPHRASE"):
            monkeypatch.setenv(name, f"value_for_{name}_long_enough")
        text = (
            "value_for_GH_TOKEN_long_enough "
            "value_for_MY_AUTH_TOKEN_long_enough "
            "value_for_SOME_API_KEY_long_enough "
            "value_for_MY_PASSPHRASE_long_enough"
        )
        out = redact_env_secrets(text)
        for name in ("GH_TOKEN", "MY_AUTH_TOKEN", "SOME_API_KEY", "MY_PASSPHRASE"):
            assert f"value_for_{name}_long_enough" not in out

    def test_case_insensitive_name_match(self, monkeypatch):
        # Lowercase env var names are unusual but legal on POSIX. The
        # redactor uses an uppercase comparison so they still match.
        monkeypatch.setenv("github_token", "ghp_lowercasename123")
        text = "leaked: ghp_lowercasename123"
        out = redact_env_secrets(text)
        assert "ghp_lowercasename123" not in out

    def test_empty_text_returns_unchanged(self):
        assert redact_env_secrets("") == ""
        assert redact_env_secrets(None) is None  # type: ignore[arg-type]

    def test_admin_opt_out_disables_scrub(self, monkeypatch):
        # Sophisticated users debugging credential helpers need raw
        # output. The opt-out env var bypasses both passes (env-value
        # scan and known-prefix sweep). Default-off so the redaction
        # stays load-bearing in normal use.
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_pretend_value_xyz")
        text = "GITHUB_TOKEN=ghp_pretend_value_xyz"

        monkeypatch.setenv("NBI_DISABLE_OUTPUT_SCRUB", "1")
        assert redact_env_secrets(text) == text  # passthrough

        monkeypatch.setenv("NBI_DISABLE_OUTPUT_SCRUB", "true")
        assert redact_env_secrets(text) == text

        # An unset / non-truthy value re-enables the scrub.
        monkeypatch.delenv("NBI_DISABLE_OUTPUT_SCRUB", raising=False)
        assert "<redacted>" in redact_env_secrets(text)
        monkeypatch.setenv("NBI_DISABLE_OUTPUT_SCRUB", "0")
        assert "<redacted>" in redact_env_secrets(text)

    def test_known_prefix_match_redacts_base64_or_derived_forms(self, monkeypatch):
        # Pass 2: catches tokens that don't match any env value (because
        # the token was passed via CLI flag, embedded in base64, or
        # produced by an upstream tool). Pin each well-known prefix.
        # Length must be >= 20 to avoid `sk-` false positives on short
        # identifiers like git refs.
        for raw_token in [
            "ghp_aaaaaaaaaaaaaaaaaaaa",
            "gho_bbbbbbbbbbbbbbbbbbbb",
            "ghs_cccccccccccccccccccc",
            "github_pat_ddddddddddddddddddd",
            "sk-ant-eeeeeeeeeeeeeeeeeeee",
            "sk-fffffffffffffffffff",
            "xoxb-gggggggggggggggggggggg",
            "AKIAhhhhhhhhhhhhhhhh",
        ]:
            assert "<redacted>" in redact_env_secrets(
                f"prefix {raw_token} suffix"
            ), raw_token

    def test_prefix_match_skips_short_lookalikes(self):
        # A 7-char git short hash and a few-char abbrev would falsely
        # match the regex without the length floor. Pin that short
        # forms pass through.
        assert redact_env_secrets("see commit ghp_abc1") == "see commit ghp_abc1"
        assert redact_env_secrets("ref sk-1234") == "ref sk-1234"


class TestExecuteCommandScrubsOutput:
    """End-to-end pin: the `execute_command` tool runs a shell command
    and returns stdout+stderr to the LLM. The output must be scrubbed
    before it reaches chat history.
    """

    @pytest.fixture
    def jupyter_root(self, tmp_path, monkeypatch):
        root = tmp_path / "workspace"
        root.mkdir()
        monkeypatch.setattr(toolsets, "get_jupyter_root_dir", lambda: str(root))
        set_jupyter_root_dir(str(root))
        return root

    def test_secret_in_stdout_is_redacted(self, jupyter_root, monkeypatch):
        # Fake a subprocess that echoes the user's GITHUB_TOKEN (the same
        # shape `env` would produce).
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_pretend_value_xyz")

        fake_result = MagicMock()
        fake_result.stdout = "GITHUB_TOKEN=ghp_pretend_value_xyz\n"
        fake_result.stderr = ""
        fake_result.returncode = 0

        tool = toolsets.execute_command._tool_function
        with patch(
            "notebook_intelligence.built_in_toolsets.subprocess.run",
            return_value=fake_result,
        ):
            result = asyncio.run(tool(command="env", working_directory="."))

        assert "ghp_pretend_value_xyz" not in result
        assert "<redacted>" in result
        # The variable name itself is fine to surface; only the value is
        # sensitive.
        assert "GITHUB_TOKEN" in result

    def test_secret_in_stderr_is_redacted(self, jupyter_root, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-pretend-aaaa")

        fake_result = MagicMock()
        fake_result.stdout = ""
        fake_result.stderr = "auth failed for key sk-ant-pretend-aaaa\n"
        fake_result.returncode = 1

        tool = toolsets.execute_command._tool_function
        with patch(
            "notebook_intelligence.built_in_toolsets.subprocess.run",
            return_value=fake_result,
        ):
            result = asyncio.run(tool(command="curl", working_directory="."))

        assert "sk-ant-pretend-aaaa" not in result

    def test_non_secret_env_not_redacted(self, jupyter_root, monkeypatch):
        # PATH and HOME etc. should pass through unchanged so debug output
        # remains legible.
        monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")

        fake_result = MagicMock()
        fake_result.stdout = "PATH=/usr/local/bin:/usr/bin\n"
        fake_result.stderr = ""
        fake_result.returncode = 0

        tool = toolsets.execute_command._tool_function
        with patch(
            "notebook_intelligence.built_in_toolsets.subprocess.run",
            return_value=fake_result,
        ):
            result = asyncio.run(tool(command="env", working_directory="."))

        assert "/usr/local/bin:/usr/bin" in result
