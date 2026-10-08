"""Tests for parse_output_limit: output-token limits a provider states when it rejects a request.

Every positive wording below was recorded from a real provider rejection (issue trackers, provider
docs, gateway test suites); the negatives are neighbouring rejections that must never be read as an
output limit.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from myrm_agent_harness.toolkits.llms.errors.output_limit import OutputLimit, parse_output_limit


def _limit(message: str) -> OutputLimit | None:
    return parse_output_limit(Exception(message))


def _tokens(message: str) -> int | None:
    limit = _limit(message)
    return None if limit is None else limit.tokens


# ---------------------------------------------------------------------------
# Model-stated ceilings: the provider names the largest max_tokens the model accepts
# ---------------------------------------------------------------------------

MODEL_CAP_WORDINGS = [
    pytest.param(
        "InternalError.Algo.InvalidParameter: Range of max_tokens should be [1, 8192]",
        8192,
        id="dashscope",
    ),
    pytest.param(
        "Invalid max_tokens value, the valid range of max_tokens is [1, 8192]",
        8192,
        id="deepseek",
    ),
    pytest.param(
        "max_tokens is too large: 20000. This model supports at most 16384 completion tokens, "
        "whereas you provided 20000.",
        16384,
        id="azure-openai",
    ),
    pytest.param(
        "max_tokens: 8192 > 4096, which is the maximum allowed number of output tokens for claude-3-5-sonnet-20240620",
        4096,
        id="anthropic",
    ),
    pytest.param(
        "max_tokens (384000) exceeds model's maximum output tokens (65536) for model deepseek-v4-flash:0731",
        65536,
        id="gateway-max-tokens",
    ),
    pytest.param(
        "Azure OpenAI API error (400): max_completion_tokens (384000) exceeds model's maximum output tokens (65536)",
        65536,
        id="gateway-max-completion-tokens",
    ),
    pytest.param(
        "OpenAI API error (400): 400 max_new_tokens (384000) exceeds model's maximum output tokens (65536)",
        65536,
        id="gateway-max-new-tokens",
    ),
    pytest.param(
        "The parameter `max_tokens` specified in the request are not valid: integer above maximum value, "
        "expected a value <= 32768, but got 65536 instead.",
        32768,
        id="volcengine-ark-max-tokens",
    ),
    pytest.param(
        "The parameter `max_completion_tokens` specified in the request are not valid: integer above maximum "
        "value, expected a value <= 12288, but got 32000 instead. Request id: 0217752964393142fa50af54af66c5cf",
        12288,
        id="volcengine-ark-max-completion-tokens",
    ),
    pytest.param(
        "max_completion_tokens must be less than or equal to 40960, the maximum value for max_completion_tokens "
        "is less than the context_window for this model",
        40960,
        id="groq",
    ),
]


class TestModelStatedCeilings:
    @pytest.mark.parametrize(("message", "expected"), MODEL_CAP_WORDINGS)
    def test_recorded_wording_yields_the_model_ceiling(self, message: str, expected: int) -> None:
        assert _limit(message) == OutputLimit(tokens=expected, model_cap=True)

    def test_ceiling_is_read_from_the_nested_response_body(self) -> None:
        class _RejectionError(Exception):
            status_code = 400
            body: ClassVar[dict[str, dict[str, str]]] = {
                "error": {"message": "Range of max_tokens should be [1, 4096]"}
            }

        assert parse_output_limit(_RejectionError("InvalidParameter")) == OutputLimit(tokens=4096, model_cap=True)

    def test_thousands_separators_are_accepted(self) -> None:
        assert _tokens("This model supports at most 16,384 completion tokens") == 16384


# ---------------------------------------------------------------------------
# Window remainders: the provider names the context window and the prompt size
# ---------------------------------------------------------------------------


class TestAnthropicAvailableTokens:
    def test_standard(self) -> None:
        message = "max_tokens: 32768 > context_window: 200000 - input_tokens: 190000 = available_tokens: 10000"
        assert _limit(message) == OutputLimit(tokens=10000, model_cap=False)

    def test_underscore_variant(self) -> None:
        message = "max_tokens: 8192 > context_window: 128000 - input_tokens: 127000 = available_tokens: 1000"
        assert _tokens(message) == 1000

    def test_space_variant(self) -> None:
        message = "max_tokens: 4096 > context_window: 128000 - input_tokens: 126000 = available tokens: 2000"
        assert _tokens(message) == 2000


class TestAnthropicContextSum:
    def test_exceed_context_limit_sum(self) -> None:
        message = (
            "input length and `max_tokens` exceed context limit: 188240 + 21333 > 200000, "
            "decrease input length or `max_tokens` and try again"
        )
        assert _limit(message) == OutputLimit(tokens=200000 - 188240, model_cap=False)

    def test_parenthesised_sum_variant(self) -> None:
        message = "input length and max_tokens exceed context limit (i.e 156321 + 48384 > 200000)"
        assert _tokens(message) == 200000 - 156321

    def test_provider_stated_available_tokens_wins_over_the_sum(self) -> None:
        message = "input length and max_tokens exceed context limit: 200000 + 64000 > 200000, available_tokens: 8936"
        assert _tokens(message) == 8936

    def test_prompt_alone_fills_the_window(self) -> None:
        assert _tokens("input length and max_tokens exceed context limit: 205000 + 4096 > 200000") is None


class TestOpenRouterFormat:
    def test_standard_breakdown(self) -> None:
        message = (
            "This endpoint's maximum context length is 200000 tokens. "
            "However, you requested about 195000 tokens "
            "(150000 of text input, 40000 of tool input, 5000 in the output)."
        )
        assert _limit(message) == OutputLimit(tokens=10000, model_cap=False)

    def test_tight_window(self) -> None:
        message = (
            "This endpoint's maximum context length is 100000 tokens. "
            "However, you requested about 110000 tokens "
            "(90000 of text input, 5000 of tool input, 15000 in the output)."
        )
        assert _tokens(message) == 5000

    def test_no_room_returns_none(self) -> None:
        message = "maximum context length is 1000 tokens (900 of text input, 200 of tool input, 0 in the output)"
        assert _limit(message) is None


class TestOpenAISplitFormat:
    def test_messages_and_completion(self) -> None:
        message = (
            "This model's maximum context length is 4096 tokens. However, you requested 4157 tokens "
            "(62 in the messages, 4095 in the completion). Please reduce the length of the messages or completion."
        )
        assert _limit(message) == OutputLimit(tokens=4096 - 62, model_cap=False)

    def test_prompt_and_completion_variant(self) -> None:
        message = (
            "This model's maximum context length is 4097 tokens, however you requested 5360 tokens "
            "(1360 in your prompt; 4000 for the completion). Please reduce your prompt; or completion length."
        )
        assert _tokens(message) == 4097 - 1360

    def test_prompt_fills_the_window(self) -> None:
        message = (
            "This model's maximum context length is 4096 tokens. However, you requested 4157 tokens "
            "(4100 in the messages, 57 in the completion)."
        )
        assert _limit(message) is None


class TestLMStudioCharFormat:
    def test_character_based(self) -> None:
        message = (
            "This model's maximum context length is 65536 tokens. However, "
            "you requested 65536 output tokens and your prompt contains "
            "77409 characters (more than 0 characters, which is the upper "
            "bound for 0 input tokens). Please reduce the length of the "
            "input prompt or the number of requested output tokens."
        )
        assert _tokens(message) == 65536 - (77409 + 2) // 3

    def test_character_fits_within_window(self) -> None:
        message = (
            "This model's maximum context length is 65536 tokens. However, "
            "you requested 65536 output tokens and your prompt contains "
            "77409 characters."
        )
        result = _tokens(message)
        assert result is not None
        assert result + (77409 + 2) // 3 <= 65536

    def test_character_no_room(self) -> None:
        message = (
            "maximum context length is 1000 tokens. However, you requested "
            "1000 output tokens and your prompt contains 9000 characters."
        )
        assert _limit(message) is None


class TestVLLMFormat:
    def test_standard(self) -> None:
        message = (
            "This model's maximum context length is 131072 tokens. However, you "
            "requested 65536 output tokens and your prompt contains at least 65537 "
            "input tokens, for a total of at least 131073 tokens. Please reduce "
            "the length of the input prompt or the number of requested output tokens."
        )
        assert _tokens(message) == 131072 - 65537

    def test_binding_wording(self) -> None:
        message = (
            "This model's maximum context length is 102400 tokens. However, you requested 65536 output tokens "
            "and your prompt contains at least 36865 input tokens, for a total of at least 102401 tokens."
        )
        assert _limit(message) == OutputLimit(tokens=102400 - 36865, model_cap=False)

    def test_no_room(self) -> None:
        message = (
            "maximum context length is 4096 tokens. However, you requested "
            "4096 output tokens and your prompt contains at least 4100 "
            "input tokens."
        )
        assert _limit(message) is None

    def test_you_passed_input_tokens_wording(self) -> None:
        # vLLM >= 0.16 (vllm-project/vllm#33418); the numbers are adapted, the sentence structure is as recorded.
        message = (
            "You passed 400 input tokens and requested 2045 output tokens. However, the model's context length "
            "is only 2048 tokens, resulting in a maximum input length of 3 tokens."
        )
        assert _limit(message) == OutputLimit(tokens=2048 - 400, model_cap=False)


# ---------------------------------------------------------------------------
# Edge cases and rejections that are not output limits (must return None)
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_keywords_present_but_no_parseable_number(self) -> None:
        assert _limit("max_tokens exceeds available_tokens for this model") is None

    def test_equals_at_end_without_available_tokens_keyword(self) -> None:
        message = "max_tokens: 8192 > context_window: 128000 - input_tokens: 126000 = 2000"
        assert _limit(message) is None

    def test_available_tokens_zero(self) -> None:
        message = "max_tokens: 8192 > context_window: 128000 - input_tokens: 128000 = available_tokens: 0"
        assert _limit(message) is None


NOT_AN_OUTPUT_LIMIT = [
    pytest.param("prompt is too long: 205000 tokens > 200000 maximum", id="prompt-too-long"),
    pytest.param("some unrelated 400 error", id="generic-400"),
    pytest.param("rate limit exceeded: too many requests per minute", id="rate-limit"),
    pytest.param("Rate limit reached for gpt-4o: Limit 30000 tokens per min. Please try again in 6s.", id="tpm-limit"),
    pytest.param("invalid api key provided", id="auth"),
    pytest.param("context_length_exceeded: 205000 > 200000", id="context-overflow-without-numbers"),
    pytest.param("", id="empty"),
    pytest.param(
        "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.",
        id="o-series-unsupported-parameter",
    ),
    pytest.param(
        "A maximum of 4 blocks with cache_control may be provided. Found 5.",
        id="cache-control-blocks",
    ),
    pytest.param(
        "This prompt is longer than the free tier allows for a single request.",
        id="free-tier-prompt",
    ),
    pytest.param(
        "This model's maximum context length is 8192 tokens. However, your messages resulted in 9000 tokens. "
        "Please reduce the length of the messages.",
        id="prompt-alone-overflows",
    ),
    pytest.param(
        "Invalid 'n': integer above maximum value. Expected a value <= 1, but got 5 instead.",
        id="other-parameter-above-maximum",
    ),
    pytest.param("temperature must be less than or equal to 2", id="other-parameter-less-than-or-equal"),
    pytest.param(
        "Invalid 'max_tokens': integer below minimum value. Expected a value >= 1, but got 0 instead.",
        id="max-tokens-below-minimum",
    ),
]


class TestNotAnOutputLimit:
    @pytest.mark.parametrize("message", NOT_AN_OUTPUT_LIMIT)
    def test_neighbouring_rejections_are_ignored(self, message: str) -> None:
        assert _limit(message) is None
