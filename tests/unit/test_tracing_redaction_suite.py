"""Comprehensive unit test suite for TracingRedactor across all execution paths."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.tracing_redaction import (
    ExecutionPathType,
    RedactedTraceSpan,
    TraceSpanInput,
    TracingOptOutMode,
    TracingRedactor,
)


@pytest.fixture
def redactor() -> TracingRedactor:
    return TracingRedactor()


@pytest.mark.parametrize(
    "path_type",
    [
        ExecutionPathType.SUCCESS,
        ExecutionPathType.ERROR,
        ExecutionPathType.STREAMING,
        ExecutionPathType.RETRY,
        ExecutionPathType.RESUME,
    ],
)
def test_sensitive_key_and_pattern_redaction_across_all_paths(
    redactor: TracingRedactor, path_type: ExecutionPathType
) -> None:
    span_input = TraceSpanInput(
        trace_id="trace_001",
        span_id="span_001",
        path_type=path_type,
        payload={
            "api_key": "sk-proj-abc12345678901234567890",
            "password": "supersecretpassword123",
            "headers": {
                "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
            },
            "log": "Calling Slack with xoxb-123456789012-abcdefg and GitHub token ghp_123456789012345678901234567890123456",
            "safe_field": "normal_operation",
        },
        raw_error="Failed with api_key=sk-proj-secret99999999999999999999",
    )

    result: RedactedTraceSpan = redactor.sanitize_span(span_input)

    assert result.trace_id == "trace_001"
    assert result.span_id == "span_001"
    assert result.path_type == path_type
    assert result.is_dropped is False
    assert result.redaction_count > 0

    # Verify sensitive keys were masked
    assert result.sanitized_payload["api_key"] == "[REDACTED_SENSITIVE_FIELD]"
    assert result.sanitized_payload["password"] == "[REDACTED_SENSITIVE_FIELD]"
    headers = result.sanitized_payload["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "[REDACTED_SENSITIVE_FIELD]"

    # Verify token patterns in text were masked
    log_text = str(result.sanitized_payload["log"])
    assert "xoxb-" not in log_text
    assert "[REDACTED_SLACK_TOKEN]" in log_text
    assert "ghp_" not in log_text
    assert "[REDACTED_GITHUB_TOKEN]" in log_text

    # Verify safe field was preserved
    assert result.sanitized_payload["safe_field"] == "normal_operation"

    # Verify error message was redacted
    assert result.sanitized_error is not None
    assert "sk-proj-secret" not in result.sanitized_error
    assert (
        "[REDACTED_API_KEY]" in result.sanitized_error
        or "[REDACTED]" in result.sanitized_error
    )


def test_opt_out_drop_trace_mode(redactor: TracingRedactor) -> None:
    span_input = TraceSpanInput(
        trace_id="trace_opt_out",
        span_id="span_drop",
        path_type=ExecutionPathType.SUCCESS,
        payload={"query": "private medical search"},
        opt_out_requested=True,
    )

    result = redactor.sanitize_span(
        span_input, opt_out_mode_override=TracingOptOutMode.DROP_TRACE
    )
    assert result.is_dropped is True
    assert result.sanitized_payload == {}
    assert result.sanitized_error is None
    assert result.policy_applied == "opt_out_drop"


def test_opt_out_mandatory_redaction_mode(redactor: TracingRedactor) -> None:
    span_input = TraceSpanInput(
        trace_id="trace_opt_out_redact",
        span_id="span_redact",
        path_type=ExecutionPathType.STREAMING,
        payload={
            "token": "sk-123456789012345678901234",
            "metric": 42,
        },
        opt_out_requested=True,
    )

    result = redactor.sanitize_span(
        span_input, opt_out_mode_override=TracingOptOutMode.REDACT_MANDATORY
    )
    assert result.is_dropped is False
    assert result.sanitized_payload["token"] == "[REDACTED_API_KEY]"
    assert result.sanitized_payload["metric"] == 42
    assert result.policy_applied == "redaction_enforced"


def test_nested_list_and_dict_redaction(redactor: TracingRedactor) -> None:
    span_input = TraceSpanInput(
        trace_id="trace_nested",
        span_id="span_nested",
        path_type=ExecutionPathType.RETRY,
        payload={
            "users": [
                {"name": "Alice", "password": "alicepassword"},
                {"name": "Bob", "secret": "bobsecret"},
            ],
            "retry_messages": [
                "Attempt 1 failed with api_key=sk-111111111111111111111111",
                "Attempt 2 succeeded",
            ],
        },
    )

    result = redactor.sanitize_span(span_input)
    users = result.sanitized_payload["users"]
    assert isinstance(users, list)
    assert users[0]["password"] == "[REDACTED_SENSITIVE_FIELD]"
    assert users[1]["secret"] == "[REDACTED_SENSITIVE_FIELD]"

    retry_msgs = result.sanitized_payload["retry_messages"]
    assert isinstance(retry_msgs, list)
    assert "sk-1111" not in str(retry_msgs[0])
