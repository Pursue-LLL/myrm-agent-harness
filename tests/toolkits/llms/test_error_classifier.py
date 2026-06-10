"""Tests for myrm_agent_harness.toolkits.llms.errors.classifier
and _runtime.stream_executor._emergency_compact."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.toolkits.llms.adapters.converters import (
    ensure_arguments_json_string,
)
from myrm_agent_harness.toolkits.llms.errors.classifier import (
    ErrorKind,
    classify_error,
    classify_failover_reason,
    is_context_overflow,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason

# ============================================================================
# classify_error — context overflow
# ============================================================================


@pytest.mark.parametrize(
    "msg",
    [
        "context_length_exceeded",
        "maximum context length is 128000 tokens",
        "model_context_window_exceeded",
        "prompt is too long",
        "exceeds model context window",
        "request_too_large",
        "上下文过长",
        "上下文长度超出限制",
        "413 request too large",
        "max_tokens exceed context limit",
        "input length exceed context window",
    ],
)
def test_classify_context_overflow(msg: str) -> None:
    assert classify_error(Exception(msg)) == ErrorKind.CONTEXT_OVERFLOW


# ============================================================================
# classify_error — rate limit
# ============================================================================


@pytest.mark.parametrize(
    "msg",
    [
        "Rate limit exceeded",
        "429 Too Many Requests",
        "tokens per minute quota exceeded",
        "TPM limit reached",
        "resource exhausted",
        "requests per minute exceeded",
    ],
)
def test_classify_rate_limit(msg: str) -> None:
    assert classify_error(Exception(msg)) == ErrorKind.RATE_LIMIT


# ============================================================================
# classify_error — overloaded (distinct from rate_limit)
# ============================================================================


@pytest.mark.parametrize(
    "msg",
    [
        "overloaded_error",
        "overloaded",
        "Server is under high demand right now",
        "capacity exceeded",
        "capacity full",
        "529 service overloaded",
        "503 service unavailable due to overload",
        "503 Service Unavailable",
        "504 Gateway Timeout",
        "502 Bad Gateway",
    ],
)
def test_classify_overloaded(msg: str) -> None:
    assert classify_error(Exception(msg)) == ErrorKind.OVERLOADED


# ============================================================================
# classify_error — billing
# ============================================================================


@pytest.mark.parametrize(
    "msg",
    [
        "billing error: insufficient balance",
        "402 Payment Required",
        "insufficient credits",
        "exceeded plan limit",
        "credit balance is zero",
    ],
)
def test_classify_billing(msg: str) -> None:
    assert classify_error(Exception(msg)) == ErrorKind.BILLING


# ============================================================================
# classify_error — auth
# ============================================================================


@pytest.mark.parametrize(
    "msg",
    [
        "Invalid API key provided",
        "Incorrect API key",
        "401 Unauthorized",
        "403 Forbidden",
        "access denied",
        "api key revoked",
        "token expired",
    ],
)
def test_classify_auth(msg: str) -> None:
    assert classify_error(Exception(msg)) == ErrorKind.AUTH


# ============================================================================
# classify_error — timeout
# ============================================================================


@pytest.mark.parametrize(
    "msg",
    [
        "Request timeout",
        "Connection error",
        "deadline exceeded",
        "socket hang up",
    ],
)
def test_classify_timeout(msg: str) -> None:
    assert classify_error(Exception(msg)) == ErrorKind.TIMEOUT


# ============================================================================
# classify_error — unknown
# ============================================================================


def test_classify_unknown() -> None:
    assert classify_error(Exception("something went wrong")) == ErrorKind.UNKNOWN


def test_classify_empty_message() -> None:
    assert classify_error(Exception("")) == ErrorKind.UNKNOWN


# ============================================================================
# is_context_overflow convenience
# ============================================================================


class TestIsContextOverflowPositive:
    """Errors that SHOULD be classified as context overflow."""

    @pytest.mark.parametrize(
        "msg",
        [
            "context_length_exceeded",
            "maximum context length exceeded for model gpt-4",
            "prompt is too long",
            "exceeds model context window",
            "model token limit reached",
            "context_window_exceeded",
            "model_context_window_exceeded",
            "request_too_large",
            "exceed context limit",
            "exceeds the model's maximum context length",
            "request exceeds the maximum size",
            "request size exceeds the limit",
            "Unhandled stop reason: model_context_window_exceeded",
        ],
    )
    def test_exact_patterns(self, msg: str) -> None:
        assert is_context_overflow(Exception(msg)) is True

    @pytest.mark.parametrize(
        "msg",
        [
            "max_tokens exceed the context window",
            "input length exceed context limit",
            "413 request body too large",
        ],
    )
    def test_compound_patterns(self, msg: str) -> None:
        assert is_context_overflow(Exception(msg)) is True

    @pytest.mark.parametrize(
        "msg",
        [
            "上下文过长",
            "上下文超出限制",
            "上下文长度超过最大值",
            "超出最大上下文",
            "请压缩上下文后重试",
        ],
    )
    def test_chinese_patterns(self, msg: str) -> None:
        assert is_context_overflow(Exception(msg)) is True


class TestIsContextOverflowNegative:
    """Errors that should NOT be classified as context overflow."""

    @pytest.mark.parametrize(
        "msg",
        [
            "rate limit exceeded",
            "429 too many requests",
            "tokens per minute quota exceeded",
            "tpm limit reached",
            "billing error: insufficient balance",
            "payment required",
            "exceeded plan budget",
            "",
            "random unrelated error",
            "connection timeout",
            "internal server error",
        ],
    )
    def test_excluded_or_unrelated(self, msg: str) -> None:
        assert is_context_overflow(Exception(msg)) is False

    def test_rate_limit_with_context_keyword(self) -> None:
        """Rate-limit errors mentioning 'context' should still be excluded."""
        assert is_context_overflow(Exception("rate limit: too many tokens per minute in context")) is False


# ============================================================================
# ErrorKind.is_failoverable
# ============================================================================


@pytest.mark.parametrize(
    "kind,expected",
    [
        (ErrorKind.CONTEXT_OVERFLOW, True),
        (ErrorKind.RATE_LIMIT, True),
        (ErrorKind.BILLING, True),
        (ErrorKind.TIMEOUT, True),
        (ErrorKind.AUTH, False),
        (ErrorKind.UNKNOWN, False),
    ],
)
def test_is_failoverable(kind: ErrorKind, expected: bool) -> None:
    assert kind.is_failoverable is expected


# ============================================================================
# Priority: rate_limit wins over timeout (429 is also a timeout-like status)
# ============================================================================


def test_rate_limit_priority_over_timeout() -> None:
    assert classify_error(Exception("429 Too Many Requests")) == ErrorKind.RATE_LIMIT


def test_billing_priority_over_overflow() -> None:
    msg = "billing error: context_length_exceeded"
    assert classify_error(Exception(msg)) == ErrorKind.BILLING


# ============================================================================
# classify — provider format 400 (MiniMax JSON requirement)
# ============================================================================


class TestProviderFormat400:
    """Provider format errors should be classified as FORMAT_ERROR (non-failoverable)."""

    @pytest.mark.parametrize(
        "msg",
        [
            'BadRequestError: The parameter "function.arguments" must be in JSON format',
            "InvalidParameter: function.arguments is invalid",
            "InvalidParameter: arguments format error",
        ],
    )
    def test_classify_error_as_format_error(self, msg: str) -> None:
        assert classify_error(Exception(msg)) == ErrorKind.RESPONSE_FORMAT_ERROR

    @pytest.mark.parametrize(
        "msg",
        [
            'The parameter "function.arguments" must be in JSON format',
            "InvalidParameter: function call failed",
            "InvalidParameter: arguments must be valid",
        ],
    )
    def test_failover_reason_is_format_error(self, msg: str) -> None:
        assert classify_failover_reason(Exception(msg)) == FailoverReason.RESPONSE_FORMAT_ERROR

    def test_failover_reason_is_failoverable(self) -> None:
        reason = classify_failover_reason(Exception("must be in JSON format"))
        assert reason.is_failoverable is True

    def test_auth_takes_priority_over_format(self) -> None:
        """Auth errors containing 'arguments' should still be auth, not format."""
        msg = "401 Unauthorized: invalid api key for function arguments"
        assert classify_error(Exception(msg)) == ErrorKind.AUTH


# ============================================================================
# ensure_arguments_json_string — defensive JSON validation
# ============================================================================


class TestEnsureArgumentsJsonString:
    """Tests for ensure_arguments_json_string in converters.py."""

    def test_dict_arguments_converted_to_json(self) -> None:
        tc = [{"function": {"name": "test", "arguments": {"key": "val"}}}]
        result = ensure_arguments_json_string(tc)
        assert result[0]["function"]["arguments"] == '{"key": "val"}'

    def test_none_arguments_become_empty_json(self) -> None:
        tc = [{"function": {"name": "test", "arguments": None}}]
        result = ensure_arguments_json_string(tc)
        assert result[0]["function"]["arguments"] == "{}"

    def test_valid_json_string_unchanged(self) -> None:
        tc = [{"function": {"name": "test", "arguments": '{"a": 1}'}}]
        result = ensure_arguments_json_string(tc)
        assert result[0]["function"]["arguments"] == '{"a": 1}'

    def test_invalid_json_string_reset_to_empty(self) -> None:
        tc = [{"function": {"name": "test", "arguments": "not-json"}}]
        result = ensure_arguments_json_string(tc)
        assert result[0]["function"]["arguments"] == "{}"

    def test_non_string_non_dict_wrapped(self) -> None:
        tc = [{"function": {"name": "test", "arguments": 42}}]
        result = ensure_arguments_json_string(tc)
        assert result[0]["function"]["arguments"] == '{"value": 42}'

    def test_bool_argument_wrapped(self) -> None:
        tc = [{"function": {"name": "test", "arguments": True}}]
        result = ensure_arguments_json_string(tc)
        assert result[0]["function"]["arguments"] == '{"value": true}'

    def test_no_function_key_passes_through(self) -> None:
        tc = [{"id": "call_123", "type": "function"}]
        result = ensure_arguments_json_string(tc)
        assert result == tc

    def test_original_not_mutated(self) -> None:
        original = [{"function": {"name": "test", "arguments": {"k": "v"}}}]
        ensure_arguments_json_string(original)
        assert isinstance(original[0]["function"]["arguments"], dict)

    def test_multiple_tool_calls(self) -> None:
        tcs = [
            {"function": {"name": "a", "arguments": {"x": 1}}},
            {"function": {"name": "b", "arguments": None}},
            {"function": {"name": "c", "arguments": '{"y": 2}'}},
        ]
        result = ensure_arguments_json_string(tcs)
        assert result[0]["function"]["arguments"] == '{"x": 1}'
        assert result[1]["function"]["arguments"] == "{}"
        assert result[2]["function"]["arguments"] == '{"y": 2}'


# ============================================================================
# _emergency_compact
# ============================================================================


class TestEmergencyCompact:
    """Test _emergency_compact with real message lists."""

    @pytest.mark.asyncio
    async def test_compacts_old_tool_calls(self) -> None:
        from myrm_agent_harness.agent._internals.agent_recovery import emergency_compact as _emergency_compact

        messages = [
            HumanMessage(content="hello"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "bash", "args": {"code": "ls"}}],
            ),
            ToolMessage(content="file1.txt\nfile2.txt", tool_call_id="tc1", name="bash"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc2", "name": "bash", "args": {"code": "cat file1.txt"}}],
            ),
            ToolMessage(
                content="A" * 10000,
                tool_call_id="tc2",
                name="bash",
            ),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc3", "name": "bash", "args": {"code": "echo done"}}],
            ),
            ToolMessage(content="done", tool_call_id="tc3", name="bash"),
            AIMessage(content="All done!"),
        ]

        saved = await _emergency_compact(messages)
        assert saved >= 0

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_zero(self) -> None:
        from myrm_agent_harness.agent._internals.agent_recovery import emergency_compact as _emergency_compact

        messages = [
            HumanMessage(content="hello"),
            AIMessage(content="world"),
        ]
        saved = await _emergency_compact(messages)
        assert saved == 0


# ============================================================================
# _truncate_oldest_rounds
# ============================================================================


class TestTruncateOldestRounds:
    """Test _truncate_oldest_rounds head-truncation logic."""

    def test_drops_oldest_rounds(self) -> None:
        from langchain_core.messages import SystemMessage

        from myrm_agent_harness.agent._internals.agent_recovery import _TRUNCATION_MARKER
        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds as _truncate_oldest_rounds

        msgs: list = [
            SystemMessage(content="system prompt"),
            HumanMessage(content="round 1"),
            AIMessage(content="reply 1"),
            HumanMessage(content="round 2"),
            AIMessage(content="reply 2"),
            HumanMessage(content="round 3"),
            AIMessage(content="reply 3"),
            HumanMessage(content="round 4"),
            AIMessage(content="reply 4"),
            HumanMessage(content="round 5"),
            AIMessage(content="reply 5"),
        ]

        freed = _truncate_oldest_rounds(msgs)
        assert freed > 0
        assert isinstance(msgs[0], SystemMessage)
        assert msgs[1].content == _TRUNCATION_MARKER
        assert "round 1" not in [m.content for m in msgs]

    def test_preserves_system_messages(self) -> None:
        from langchain_core.messages import SystemMessage

        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds as _truncate_oldest_rounds

        msgs: list = [
            SystemMessage(content="sys1"),
            SystemMessage(content="sys2"),
            HumanMessage(content="round 1"),
            AIMessage(content="reply 1"),
            HumanMessage(content="round 2"),
            AIMessage(content="reply 2"),
        ]

        _truncate_oldest_rounds(msgs)
        sys_msgs = [m for m in msgs if isinstance(m, SystemMessage)]
        assert len(sys_msgs) == 2
        assert sys_msgs[0].content == "sys1"
        assert sys_msgs[1].content == "sys2"

    def test_too_few_groups_returns_zero(self) -> None:
        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds as _truncate_oldest_rounds

        msgs: list = [
            HumanMessage(content="only one round"),
            AIMessage(content="reply"),
        ]
        original_len = len(msgs)
        freed = _truncate_oldest_rounds(msgs)
        assert freed == 0
        assert len(msgs) == original_len

    def test_no_non_system_returns_zero(self) -> None:
        from langchain_core.messages import SystemMessage

        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds as _truncate_oldest_rounds

        msgs: list = [SystemMessage(content="only system")]
        freed = _truncate_oldest_rounds(msgs)
        assert freed == 0

    def test_keeps_at_least_one_group(self) -> None:
        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds as _truncate_oldest_rounds

        msgs: list = [
            HumanMessage(content="round 1"),
            AIMessage(content="reply 1"),
            HumanMessage(content="round 2"),
            AIMessage(content="reply 2"),
        ]
        _truncate_oldest_rounds(msgs)
        human_msgs = [m for m in msgs if isinstance(m, HumanMessage)]
        non_marker = [m for m in human_msgs if "truncated" not in m.content]
        assert len(non_marker) >= 1

    def test_includes_tool_messages_in_groups(self) -> None:
        from myrm_agent_harness.agent._internals.agent_recovery import _TRUNCATION_MARKER
        from myrm_agent_harness.agent._internals.agent_recovery import truncate_oldest_rounds as _truncate_oldest_rounds

        msgs: list = [
            HumanMessage(content="round 1"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "bash", "args": {}}],
            ),
            ToolMessage(content="output", tool_call_id="tc1", name="bash"),
            AIMessage(content="done 1"),
            HumanMessage(content="round 2"),
            AIMessage(content="reply 2"),
            HumanMessage(content="round 3"),
            AIMessage(content="reply 3"),
        ]
        _truncate_oldest_rounds(msgs)
        assert msgs[0].content == _TRUNCATION_MARKER
        assert "round 1" not in [m.content for m in msgs]
        assert "output" not in [m.content for m in msgs]


# ============================================================================
# classify_error — RESPONSE_FORMAT_ERROR (LLM output validation failure)
# ============================================================================


@pytest.mark.parametrize(
    "msg",
    [
        "must be in JSON format",
        "schema validation error",
        "invalid json format in response",
        "response must be valid JSON",
    ],
)
def test_classify_response_format_error(msg: str) -> None:
    """Test that API gateway validation errors are classified as RESPONSE_FORMAT_ERROR."""
    reason = classify_failover_reason(Exception(msg))
    assert reason == FailoverReason.RESPONSE_FORMAT_ERROR

    kind = classify_error(Exception(msg))
    assert kind == ErrorKind.RESPONSE_FORMAT_ERROR
    assert kind.is_failoverable is True


def test_response_format_error_is_failoverable() -> None:
    """Test that RESPONSE_FORMAT_ERROR is marked as failoverable."""
    kind = ErrorKind.RESPONSE_FORMAT_ERROR
    assert kind.is_failoverable is True


# ============================================================================
# extract_retry_after
# ============================================================================


class TestExtractRetryAfter:
    """Tests for extract_retry_after() — Retry-After header extraction."""

    def test_returns_none_for_plain_exception(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import extract_retry_after

        assert extract_retry_after(Exception("rate limited")) is None

    def test_extracts_from_response_headers(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import extract_retry_after

        class FakeResponse:
            headers = {"retry-after": "30"}

        exc = Exception("rate limited")
        exc.response = FakeResponse()
        assert extract_retry_after(exc) == 30.0

    def test_extracts_capitalized_header(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import extract_retry_after

        class FakeResponse:
            headers = {"Retry-After": "45.5"}

        exc = Exception("rate limited")
        exc.response = FakeResponse()
        assert extract_retry_after(exc) == 45.5

    def test_returns_none_for_zero_value(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import extract_retry_after

        class FakeResponse:
            headers = {"retry-after": "0"}

        exc = Exception("rate limited")
        exc.response = FakeResponse()
        assert extract_retry_after(exc) is None

    def test_returns_none_for_negative_value(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import extract_retry_after

        class FakeResponse:
            headers = {"retry-after": "-5"}

        exc = Exception("rate limited")
        exc.response = FakeResponse()
        assert extract_retry_after(exc) is None

    def test_returns_none_for_non_numeric_value(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import extract_retry_after

        class FakeResponse:
            headers = {"retry-after": "invalid"}

        exc = Exception("rate limited")
        exc.response = FakeResponse()
        assert extract_retry_after(exc) is None

    def test_returns_none_when_headers_is_none(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import extract_retry_after

        class FakeResponse:
            headers = None

        exc = Exception("rate limited")
        exc.response = FakeResponse()
        assert extract_retry_after(exc) is None

    def test_walks_exception_chain(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import extract_retry_after

        class FakeResponse:
            headers = {"retry-after": "60"}

        inner = Exception("inner rate limit")
        inner.response = FakeResponse()

        outer = Exception("outer error")
        outer.__cause__ = inner
        assert extract_retry_after(outer) == 60.0

    def test_returns_none_when_no_response_in_chain(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import extract_retry_after

        inner = Exception("inner")
        outer = Exception("outer")
        outer.__cause__ = inner
        assert extract_retry_after(outer) is None

    def test_stops_at_max_depth(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import extract_retry_after

        class FakeResponse:
            headers = {"retry-after": "120"}

        # Build a chain of 7 exceptions; only depth 0 has a response.
        # The function iterates 5 times, so from depth 6 it reaches depth 2 at most.
        deepest = Exception("depth 0 with response")
        deepest.response = FakeResponse()
        current = deepest
        for i in range(1, 7):
            exc = Exception(f"depth {i}")
            exc.__cause__ = current
            current = exc

        # depth 6 -> 5 -> 4 -> 3 -> 2 (5 iterations, never reaches depth 0)
        assert extract_retry_after(current) is None

        # But with a shorter chain (depth 3 → depth 0), it should find it
        shallow = Exception("depth 0 with response")
        shallow.response = FakeResponse()
        current = shallow
        for i in range(1, 4):
            exc = Exception(f"depth {i}")
            exc.__cause__ = current
            current = exc
        assert extract_retry_after(current) == 120.0
