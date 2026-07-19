# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Per-turn usage footer built from the SDK's end-of-turn ResultMessage.

The SDK ends every turn with a ResultMessage carrying duration, token
usage, and cost. NBI used to drop it in the receive loop's silent else
branch, leaving users no signal of what a turn cost short of typing
/cost.
"""

import pytest
from claude_agent_sdk import ResultMessage

from notebook_intelligence.claude import (
    format_result_usage,
    _should_show_turn_cost,
)


@pytest.fixture(autouse=True)
def _clear_anthropic_env(monkeypatch):
    """Keep the cost-gate tests hermetic: the resolver now consults the
    process ANTHROPIC_* env vars, so clear them unless a test sets them."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


def _result(**overrides) -> ResultMessage:
    fields = {
        "subtype": "success",
        "duration_ms": 12_300,
        "duration_api_ms": 11_000,
        "is_error": False,
        "num_turns": 3,
        "session_id": "sess-1",
        "total_cost_usd": 0.0842,
        "usage": {
            "input_tokens": 4_200,
            "cache_read_input_tokens": 38_100,
            "cache_creation_input_tokens": 2_900,
            "output_tokens": 1_200,
        },
    }
    fields.update(overrides)
    return ResultMessage(**fields)


class TestFormatResultUsage:
    def test_formats_duration_tokens_and_cost(self):
        line = format_result_usage(_result())
        assert line == "\n\n*12.3s · 45.2K in (38.1K cached) / 1.2K out · $0.0842*"

    def test_error_results_produce_no_footer(self):
        assert format_result_usage(_result(is_error=True)) is None

    def test_missing_usage_and_cost_produce_duration_only(self):
        line = format_result_usage(_result(usage=None, total_cost_usd=None))
        assert line == "\n\n*12.3s*"

    def test_nothing_meaningful_returns_none(self):
        result = _result(duration_ms=0, usage=None, total_cost_usd=None)
        assert format_result_usage(result) is None

    def test_zero_cost_is_omitted(self):
        # Subscription (non-API-key) sessions report 0.0 cost; showing
        # "$0.0000" would read as a billing claim, so drop the segment.
        line = format_result_usage(_result(total_cost_usd=0.0))
        assert "$" not in line
        assert "45.2K in" in line

    def test_uncached_turn_omits_cache_annotation(self):
        line = format_result_usage(
            _result(
                usage={
                    "input_tokens": 900,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "output_tokens": 150,
                }
            )
        )
        assert "cached" not in line
        assert "900 in / 150 out" in line

    def test_malformed_usage_values_are_ignored(self):
        line = format_result_usage(
            _result(
                usage={
                    "input_tokens": "not-a-number",
                    "output_tokens": None,
                    "cache_read_input_tokens": -5,
                },
                total_cost_usd="free",
            )
        )
        # Falls back to just the duration rather than crashing the turn.
        assert line == "\n\n*12.3s*"

    def test_million_scale_token_formatting(self):
        line = format_result_usage(
            _result(
                usage={
                    "input_tokens": 1_500_000,
                    "output_tokens": 2_000,
                }
            )
        )
        assert "1.5M in" in line

    def test_show_cost_false_omits_cost_but_keeps_tokens(self):
        # Non-API-key setups (subscription/enterprise/cloud endpoints)
        # can't be priced from the CLI's public list rates, so the caller
        # suppresses the dollar figure while keeping the accurate
        # duration and token counts.
        line = format_result_usage(_result(), show_cost=False)
        assert "$" not in line
        assert line == "\n\n*12.3s · 45.2K in (38.1K cached) / 1.2K out*"

    def test_show_cost_true_is_the_default(self):
        assert "$0.0842" in format_result_usage(_result())


class TestShouldShowTurnCost:
    def test_direct_key_default_endpoint_shows_cost(self):
        assert _should_show_turn_cost({"api_key": "sk-ant-xyz"}) is True

    def test_direct_key_empty_base_url_shows_cost(self):
        # Settings-panel saves an unset field as "" rather than None.
        assert _should_show_turn_cost({"api_key": "sk-ant-xyz", "base_url": ""}) is True

    def test_direct_key_explicit_anthropic_url_shows_cost(self):
        assert _should_show_turn_cost(
            {"api_key": "sk-ant-xyz", "base_url": "https://api.anthropic.com"}
        ) is True

    def test_custom_base_url_suppresses_cost(self):
        # A proxy/gateway/cloud front bills on its own terms, so the SDK's
        # public-list-price cost can't be trusted even with an API key.
        assert _should_show_turn_cost(
            {"api_key": "sk-ant-xyz", "base_url": "https://my-proxy.example.com/v1"}
        ) is False

    def test_no_api_key_suppresses_cost(self):
        # Subscription login: no key -> notional cost only.
        assert _should_show_turn_cost({"api_key": ""}) is False
        assert _should_show_turn_cost({}) is False


class TestShouldShowTurnCostEnvResolution:
    """The CLI subprocess inherits the server's ANTHROPIC_* env vars when the
    settings fields are blank, so the cost gate must consult them too."""

    def test_env_api_key_default_endpoint_shows_cost(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        assert _should_show_turn_cost({}) is True

    def test_env_custom_base_url_suppresses_cost(self, monkeypatch):
        # Key in settings, but a custom endpoint via env -> proxy billing,
        # so the SDK's list-price cost can't be trusted.
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.com")
        assert (
            _should_show_turn_cost({"api_key": "sk-ant-xyz"}) is False
        )

    def test_settings_base_url_overrides_env(self, monkeypatch):
        # Settings win over env: a custom setting suppresses cost even when
        # the env points at the first-party endpoint.
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        assert (
            _should_show_turn_cost(
                {"api_key": "sk-ant-xyz", "base_url": "https://proxy.example.com"}
            )
            is False
        )

    def test_no_key_anywhere_suppresses_cost(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert _should_show_turn_cost({}) is False


    def test_footer_starts_with_a_paragraph_break(self):
        # The footer is streamed right after the turn's final text block;
        # without a separator it concatenates onto prose that doesn't end
        # in a blank line ("Done.*12.3s ...*") and breaks the emphasis
        # markup.
        line = format_result_usage(_result())
        assert line.startswith("\n\n*")
        assert ("Done." + line).splitlines()[-1].startswith("*")
