# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Per-turn usage footer built from the SDK's end-of-turn ResultMessage.

The SDK ends every turn with a ResultMessage carrying duration, token
usage, and cost. NBI used to drop it in the receive loop's silent else
branch, leaving users no signal of what a turn cost short of typing
/cost.
"""

from claude_agent_sdk import ResultMessage

from notebook_intelligence.claude import format_result_usage


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
        assert line == "*12.3s · 45.2K in (38.1K cached) / 1.2K out · $0.0842*"

    def test_error_results_produce_no_footer(self):
        assert format_result_usage(_result(is_error=True)) is None

    def test_missing_usage_and_cost_produce_duration_only(self):
        line = format_result_usage(_result(usage=None, total_cost_usd=None))
        assert line == "*12.3s*"

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
        assert line == "*12.3s*"

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
