from myrm_agent_harness.toolkits.llms.errors.classifier import (
    ErrorKind,
    classify_error,
    classify_failover_reason,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import (
    FailoverReason,
    RecoverabilityLevel,
)


class MockAPIError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_reasoning_mandatory_detection() -> None:
    # Various mandatory reasoning errors from Anthropic / OpenAI / DeepSeek / PaaS
    examples = [
        "Thinking is mandatory for this model and cannot be disabled.",
        "Error: reasoning_effort is required and must not be disabled for o3-mini",
        "InvalidRequestError: 400 - thinking mode must be enabled for this endpoint",
        "reasoning is mandatory: reasoning_effort must be provided",
        "thinking_budget is required for claude-3-7-sonnet thinking mode",
        "reasoning_content cannot be omitted for this model",
    ]

    for msg in examples:
        exc = MockAPIError(msg, status_code=400)
        reason = classify_failover_reason(exc)
        assert reason == FailoverReason.REASONING_MANDATORY, f"Failed for msg: {msg}"
        assert classify_error(exc) == ErrorKind.FORMAT_ERROR
        assert reason.recoverability == RecoverabilityLevel.TRANSIENT


def test_non_reasoning_400_is_not_reasoning_mandatory() -> None:
    exc = MockAPIError("Invalid parameter: temperature must be between 0 and 2", status_code=400)
    assert classify_failover_reason(exc) != FailoverReason.REASONING_MANDATORY
