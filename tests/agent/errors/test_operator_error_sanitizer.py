"""Unit tests for Operator Error Sanitizer and internal cause separation."""

import pytest

from myrm_agent_harness.agent.errors import (
    OperatorErrorCode,
    OperatorErrorSanitizer,
    SanitizedOperatorError,
)


def test_sanitize_standard_exception_path_and_traceback_stripping():
    """Test stripping internal traceback and file path from raw exceptions."""
    raw_error_text = (
        "Traceback (most recent call last):\n"
        '  File "/Users/yululiu/projects/AI/open-perplexity/myrm_agent_harness/runtime.py", line 42, in run\n'
        "    raise PermissionError('Access denied to /var/secrets/token.json')\n"
        "PermissionError: Access denied to /var/secrets/token.json"
    )

    sanitized = OperatorErrorSanitizer.sanitize(raw_error_text)

    assert sanitized.ok is False
    assert sanitized.code == OperatorErrorCode.PERMISSION_DENIED
    assert sanitized.category == "SECURITY"
    assert "/Users/yululiu" not in sanitized.message
    assert "Traceback" not in sanitized.message
    assert "<redacted_path>" in sanitized.message or "Access denied" in sanitized.message
    assert "Check file or API access permissions" in sanitized.hint


def test_sanitize_timeout_and_agent_busy():
    """Test timeout and agent busy error classification."""
    timeout_err = TimeoutError("Execution timed out after 30 seconds")
    sanitized_timeout = OperatorErrorSanitizer.sanitize(timeout_err)
    assert sanitized_timeout.code == OperatorErrorCode.TIMEOUT
    assert sanitized_timeout.category == "TIMEOUT"

    busy_err = RuntimeError("AgentBusyError: Agent is currently executing a subtask")
    sanitized_busy = OperatorErrorSanitizer.sanitize(busy_err)
    assert sanitized_busy.code == OperatorErrorCode.AGENT_BUSY
    assert sanitized_busy.category == "AGENT"


def test_to_client_dict_excludes_internal_cause():
    """Test to_client_dict does not leak internal_cause to frontend."""
    err = ValueError("Invalid tool parameter")
    sanitized = OperatorErrorSanitizer.sanitize(err)

    client_dict = sanitized.to_client_dict()
    assert "internal_cause" not in client_dict
    assert client_dict["ok"] is False
    assert "code" in client_dict
    assert "message" in client_dict
    assert "hint" in client_dict
