"""Tests for parse_available_output_tokens_from_error — 5 provider formats.

Validates that the output-cap parser correctly extracts available tokens from
Anthropic, OpenRouter, vLLM, LM Studio, and DashScope error messages.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.errors.classifier import (
    parse_available_output_tokens_from_error,
)


def _make_exc(msg: str) -> Exception:
    """Create a minimal Exception carrying only a message string."""
    return Exception(msg)


# ---------------------------------------------------------------------------
# Format 1: Anthropic  "available_tokens: N"
# ---------------------------------------------------------------------------


class TestAnthropicFormat:
    def test_standard(self) -> None:
        exc = _make_exc(
            "max_tokens: 32768 > context_window: 200000 "
            "- input_tokens: 190000 = available_tokens: 10000"
        )
        assert parse_available_output_tokens_from_error(exc) == 10000

    def test_underscore_variant(self) -> None:
        exc = _make_exc(
            "max_tokens: 8192 > context_window: 128000 "
            "- input_tokens: 127000 = available_tokens: 1000"
        )
        assert parse_available_output_tokens_from_error(exc) == 1000

    def test_space_variant(self) -> None:
        exc = _make_exc(
            "max_tokens: 4096 > context_window: 128000 "
            "- input_tokens: 126000 = available tokens: 2000"
        )
        assert parse_available_output_tokens_from_error(exc) == 2000


# ---------------------------------------------------------------------------
# Format 2: OpenRouter / Nous  "(A of text input, B of tool input, C in the output)"
# ---------------------------------------------------------------------------


class TestOpenRouterFormat:
    def test_standard_breakdown(self) -> None:
        exc = _make_exc(
            "This endpoint's maximum context length is 200000 tokens. "
            "However, you requested about 195000 tokens "
            "(150000 of text input, 40000 of tool input, 5000 in the output)."
        )
        assert parse_available_output_tokens_from_error(exc) == 10000

    def test_tight_window(self) -> None:
        exc = _make_exc(
            "This endpoint's maximum context length is 100000 tokens. "
            "However, you requested about 110000 tokens "
            "(90000 of text input, 5000 of tool input, 15000 in the output)."
        )
        assert parse_available_output_tokens_from_error(exc) == 5000

    def test_no_room_returns_none(self) -> None:
        exc = _make_exc(
            "maximum context length is 1000 tokens "
            "(900 of text input, 200 of tool input, 0 in the output)"
        )
        assert parse_available_output_tokens_from_error(exc) is None


# ---------------------------------------------------------------------------
# Format 3: LM Studio / llama.cpp (character-based prompt size)
# ---------------------------------------------------------------------------


class TestLMStudioCharFormat:
    def test_character_based(self) -> None:
        exc = _make_exc(
            "This model's maximum context length is 65536 tokens. However, "
            "you requested 65536 output tokens and your prompt contains "
            "77409 characters (more than 0 characters, which is the upper "
            "bound for 0 input tokens). Please reduce the length of the "
            "input prompt or the number of requested output tokens."
        )
        result = parse_available_output_tokens_from_error(exc)
        assert result is not None
        est_input = (77409 + 2) // 3
        assert result == 65536 - est_input

    def test_character_fits_within_window(self) -> None:
        exc = _make_exc(
            "This model's maximum context length is 65536 tokens. However, "
            "you requested 65536 output tokens and your prompt contains "
            "77409 characters."
        )
        result = parse_available_output_tokens_from_error(exc)
        assert result is not None
        assert result + (77409 + 2) // 3 <= 65536

    def test_character_no_room(self) -> None:
        exc = _make_exc(
            "maximum context length is 1000 tokens. However, you requested "
            "1000 output tokens and your prompt contains 9000 characters."
        )
        assert parse_available_output_tokens_from_error(exc) is None


# ---------------------------------------------------------------------------
# Format 4: vLLM (token-based prompt size)
# ---------------------------------------------------------------------------


class TestVLLMFormat:
    def test_standard(self) -> None:
        exc = _make_exc(
            "This model's maximum context length is 131072 tokens. However, you "
            "requested 65536 output tokens and your prompt contains at least 65537 "
            "input tokens, for a total of at least 131073 tokens. Please reduce "
            "the length of the input prompt or the number of requested output tokens."
        )
        assert parse_available_output_tokens_from_error(exc) == 131072 - 65537

    def test_no_room(self) -> None:
        exc = _make_exc(
            "maximum context length is 4096 tokens. However, you requested "
            "4096 output tokens and your prompt contains at least 4100 "
            "input tokens."
        )
        assert parse_available_output_tokens_from_error(exc) is None


# ---------------------------------------------------------------------------
# Format 5: DashScope / Alibaba (Qwen)  "Range of max_tokens should be [1, N]"
# ---------------------------------------------------------------------------


class TestDashScopeFormat:
    def test_standard_range(self) -> None:
        exc = _make_exc("Range of max_tokens should be [1, 65536]")
        assert parse_available_output_tokens_from_error(exc) == 65536

    def test_small_range(self) -> None:
        exc = _make_exc("Range of max_tokens should be [1, 4096]")
        assert parse_available_output_tokens_from_error(exc) == 4096


# ---------------------------------------------------------------------------
# Edge cases: guard passes but no regex matches
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_keywords_present_but_no_parseable_number(self) -> None:
        exc = _make_exc(
            "max_tokens exceeds available_tokens for this model"
        )
        assert parse_available_output_tokens_from_error(exc) is None

    def test_equals_at_end_without_available_tokens_keyword(self) -> None:
        exc = _make_exc(
            "max_tokens: 8192 > context_window: 128000 "
            "- input_tokens: 126000 = 2000"
        )
        assert parse_available_output_tokens_from_error(exc) is None

    def test_available_tokens_zero(self) -> None:
        exc = _make_exc(
            "max_tokens: 8192 > context_window: 128000 "
            "- input_tokens: 128000 = available_tokens: 0"
        )
        assert parse_available_output_tokens_from_error(exc) is None


# ---------------------------------------------------------------------------
# Non-output-cap errors (must return None)
# ---------------------------------------------------------------------------


class TestNonOutputCapErrors:
    def test_prompt_too_long(self) -> None:
        exc = _make_exc("prompt is too long: 205000 tokens > 200000 maximum")
        assert parse_available_output_tokens_from_error(exc) is None

    def test_generic_400(self) -> None:
        exc = _make_exc("some unrelated 400 error")
        assert parse_available_output_tokens_from_error(exc) is None

    def test_rate_limit(self) -> None:
        exc = _make_exc("rate limit exceeded: too many requests per minute")
        assert parse_available_output_tokens_from_error(exc) is None

    def test_auth_error(self) -> None:
        exc = _make_exc("invalid api key provided")
        assert parse_available_output_tokens_from_error(exc) is None

    def test_context_overflow_without_available(self) -> None:
        exc = _make_exc("context_length_exceeded: 205000 > 200000")
        assert parse_available_output_tokens_from_error(exc) is None

    def test_empty_message(self) -> None:
        exc = _make_exc("")
        assert parse_available_output_tokens_from_error(exc) is None
