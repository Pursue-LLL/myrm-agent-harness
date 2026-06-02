import json

from myrm_agent_harness.toolkits.llms.errors.classifier import (
    ErrorKind,
    classify_error,
    classify_failover_reason,
    normalize_provider_error,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason


# Mock exception classes for testing
class APIStatusError(Exception):
    def __init__(self, message, status_code, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class APITimeoutError(Exception):
    def __init__(self, message):
        super().__init__(message)


def test_normalize_provider_error_simple():
    exc = Exception("Simple error")
    normalized = normalize_provider_error(exc)
    assert normalized.status_code is None
    assert "simple error" in normalized.message


def test_normalize_provider_error_with_status_code():
    exc = APIStatusError("Not found", 404, {"error": {"message": "Model not found"}})
    normalized = normalize_provider_error(exc)
    assert normalized.status_code == 404
    assert "model not found" in normalized.message


def test_normalize_provider_error_nested_metadata_raw():
    # Simulate OpenRouter nested error
    inner_error = json.dumps({"error": {"message": "context length exceeded"}})
    body = {"error": {"message": "Upstream error", "metadata": {"raw": inner_error}}}
    exc = APIStatusError("Upstream error", 400, body)
    normalized = normalize_provider_error(exc)
    assert "context length exceeded" in normalized.message
    assert normalized.status_code == 400

    # Ensure it classifies correctly as CONTEXT_OVERFLOW
    assert classify_error(exc) == ErrorKind.CONTEXT_OVERFLOW
    assert classify_failover_reason(exc) == FailoverReason.CONTEXT_OVERFLOW


def test_classify_safety_block():
    exc = Exception("Request was rejected as a result of the safety system")
    assert classify_error(exc) == ErrorKind.SAFETY_BLOCK
    assert classify_failover_reason(exc) == FailoverReason.SAFETY_BLOCK

    exc2 = Exception("content_policy_violation")
    assert classify_error(exc2) == ErrorKind.SAFETY_BLOCK


def test_classify_model_not_found():
    exc = Exception("Model does not exist")
    assert classify_error(exc) == ErrorKind.MODEL_NOT_FOUND
    assert classify_failover_reason(exc) == FailoverReason.MODEL_NOT_FOUND


def test_disambiguate_usage_limit():
    # Transient usage limit -> RATE_LIMIT
    exc1 = Exception("usage limit exceeded. try again in 5 minutes")
    assert classify_error(exc1) == ErrorKind.RATE_LIMIT

    # Hard usage limit -> BILLING
    exc2 = Exception("usage limit exceeded. please upgrade your plan")
    assert classify_error(exc2) == ErrorKind.BILLING


def test_fallback_status_code_probes():
    # 400 fallback -> FORMAT_ERROR
    exc_400 = APIStatusError("Some weird error", 400, None)
    assert classify_error(exc_400) == ErrorKind.FORMAT_ERROR

    # 413 fallback -> CONTEXT_OVERFLOW
    exc_413 = APIStatusError("Payload", 413, None)
    assert classify_error(exc_413) == ErrorKind.CONTEXT_OVERFLOW

    # 429 fallback -> RATE_LIMIT
    exc_429 = APIStatusError("Slow down", 429, None)
    assert classify_error(exc_429) == ErrorKind.RATE_LIMIT

    # 500 fallback -> OVERLOADED
    exc_500 = APIStatusError("Internal", 500, None)
    assert classify_error(exc_500) == ErrorKind.OVERLOADED


def test_timeout_fallback():
    exc = APITimeoutError("unexpected eof")
    assert classify_error(exc) == ErrorKind.TIMEOUT


def test_format_error():
    exc = Exception("schema validation error in arguments")
    assert classify_error(exc) == ErrorKind.RESPONSE_FORMAT_ERROR


def test_empty_error():
    exc = Exception("")
    assert classify_error(exc) == ErrorKind.UNKNOWN
