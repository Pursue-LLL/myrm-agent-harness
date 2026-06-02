"""Tests for newly added error classification types (A1 competitive analysis).

Covers: THINKING_SIGNATURE, IMAGE_TOO_LARGE, LONG_CONTEXT_TIER, PROVIDER_POLICY_BLOCKED
"""

import pytest

from myrm_agent_harness.toolkits.llms.errors.classifier import (
    ErrorKind,
    classify_error,
    classify_failover_reason,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import (
    FailoverReason,
    RecoverabilityLevel,
    get_probe_policy,
)


class _FakeError(Exception):
    def __init__(self, msg: str, status_code: int | None = None) -> None:
        super().__init__(msg)
        self.status_code = status_code


# ============================================================================
# THINKING_SIGNATURE
# ============================================================================


class TestThinkingSignature:
    """Anthropic thinking block signature invalid (400)."""

    def test_classify_thinking_signature_basic(self) -> None:
        exc = _FakeError("the thinking block signature is not valid", status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.THINKING_SIGNATURE

    def test_classify_thinking_signature_variant(self) -> None:
        exc = _FakeError("Invalid signature for thinking content block", status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.THINKING_SIGNATURE

    def test_thinking_signature_without_400_not_matched(self) -> None:
        exc = _FakeError("signature thinking", status_code=500)
        assert classify_failover_reason(exc) != FailoverReason.THINKING_SIGNATURE

    def test_thinking_signature_maps_to_format_error_kind(self) -> None:
        exc = _FakeError("thinking block signature invalid", status_code=400)
        assert classify_error(exc) == ErrorKind.FORMAT_ERROR

    def test_thinking_signature_is_transient(self) -> None:
        assert FailoverReason.THINKING_SIGNATURE.recoverability == RecoverabilityLevel.TRANSIENT

    def test_thinking_signature_probe_policy_disabled(self) -> None:
        policy = get_probe_policy(FailoverReason.THINKING_SIGNATURE)
        assert not policy.enabled

    def test_thinking_signature_not_failoverable(self) -> None:
        assert not FailoverReason.THINKING_SIGNATURE.is_failoverable

    def test_generic_400_still_format_error(self) -> None:
        exc = _FakeError("something went wrong", status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.FORMAT_ERROR

    def test_thinking_signature_priority_over_generic_400(self) -> None:
        exc = _FakeError("Bad request: signature of thinking block failed", status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.THINKING_SIGNATURE


# ============================================================================
# IMAGE_TOO_LARGE
# ============================================================================


class TestImageTooLarge:
    """Provider per-image size limit exceeded."""

    @pytest.mark.parametrize(
        "msg",
        [
            "image exceeds 5 MB maximum: 8388608 bytes",
            "Image too large for processing",
            "image_too_large",
            "image size exceeds the maximum allowed",
            "exceeds the per-image limit of 20MB",
        ],
    )
    def test_classify_image_too_large(self, msg: str) -> None:
        exc = _FakeError(msg, status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.IMAGE_TOO_LARGE

    def test_image_too_large_is_transient(self) -> None:
        assert FailoverReason.IMAGE_TOO_LARGE.recoverability == RecoverabilityLevel.TRANSIENT

    def test_image_too_large_not_failoverable(self) -> None:
        assert not FailoverReason.IMAGE_TOO_LARGE.is_failoverable

    def test_image_too_large_priority_over_format_error(self) -> None:
        exc = _FakeError("image exceeds 5 MB maximum", status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.IMAGE_TOO_LARGE

    def test_image_too_large_without_status_code(self) -> None:
        exc = _FakeError("image exceeds 5 MB maximum")
        assert classify_failover_reason(exc) == FailoverReason.IMAGE_TOO_LARGE


# ============================================================================
# LONG_CONTEXT_TIER
# ============================================================================


class TestLongContextTier:
    """Anthropic subscription tier gate (429)."""

    def test_classify_long_context_tier(self) -> None:
        exc = _FakeError(
            "Extra usage is required for long context requests on claude-3-5-sonnet",
            status_code=429,
        )
        assert classify_failover_reason(exc) == FailoverReason.LONG_CONTEXT_TIER

    def test_long_context_tier_variant(self) -> None:
        exc = _FakeError(
            "extra usage is needed for long context on this model",
            status_code=429,
        )
        assert classify_failover_reason(exc) == FailoverReason.LONG_CONTEXT_TIER

    def test_long_context_tier_not_matched_without_429(self) -> None:
        exc = _FakeError("extra usage required for long context", status_code=400)
        assert classify_failover_reason(exc) != FailoverReason.LONG_CONTEXT_TIER

    def test_long_context_tier_is_permanent(self) -> None:
        assert FailoverReason.LONG_CONTEXT_TIER.recoverability == RecoverabilityLevel.PERMANENT

    def test_long_context_tier_maps_to_context_overflow(self) -> None:
        exc = _FakeError(
            "Extra usage is required for long context requests",
            status_code=429,
        )
        assert classify_error(exc) == ErrorKind.CONTEXT_OVERFLOW

    def test_generic_429_still_rate_limit(self) -> None:
        exc = _FakeError("too many requests", status_code=429)
        assert classify_failover_reason(exc) == FailoverReason.RATE_LIMIT

    def test_long_context_tier_priority_over_rate_limit(self) -> None:
        exc = _FakeError(
            "Rate limit: Extra usage is required for long context requests",
            status_code=429,
        )
        assert classify_failover_reason(exc) == FailoverReason.LONG_CONTEXT_TIER


# ============================================================================
# PROVIDER_POLICY_BLOCKED
# ============================================================================


class TestProviderPolicyBlocked:
    """Aggregator guardrail/data policy block (e.g. OpenRouter)."""

    @pytest.mark.parametrize(
        "msg",
        [
            "No endpoints available matching your guardrail restrictions and data policy",
            "No endpoints available matching your data policy",
        ],
    )
    def test_classify_provider_policy_blocked(self, msg: str) -> None:
        exc = _FakeError(msg, status_code=404)
        assert classify_failover_reason(exc) == FailoverReason.PROVIDER_POLICY_BLOCKED

    def test_provider_policy_blocked_is_permanent(self) -> None:
        assert FailoverReason.PROVIDER_POLICY_BLOCKED.recoverability == RecoverabilityLevel.PERMANENT

    def test_provider_policy_blocked_not_failoverable(self) -> None:
        assert not FailoverReason.PROVIDER_POLICY_BLOCKED.is_failoverable

    def test_provider_policy_blocked_priority_over_model_not_found(self) -> None:
        exc = _FakeError(
            "No endpoints available matching your guardrail restrictions",
            status_code=404,
        )
        assert classify_failover_reason(exc) == FailoverReason.PROVIDER_POLICY_BLOCKED

    def test_generic_model_not_found_still_works(self) -> None:
        exc = _FakeError("model not found", status_code=404)
        assert classify_failover_reason(exc) == FailoverReason.MODEL_NOT_FOUND


# ============================================================================
# Regression: existing patterns still work
# ============================================================================


class TestRegressions:
    """Ensure existing classification behavior is preserved."""

    def test_context_overflow_unchanged(self) -> None:
        exc = _FakeError("context_length_exceeded")
        assert classify_failover_reason(exc) == FailoverReason.CONTEXT_OVERFLOW

    def test_rate_limit_unchanged(self) -> None:
        exc = _FakeError("Rate limit exceeded", status_code=429)
        assert classify_failover_reason(exc) == FailoverReason.RATE_LIMIT

    def test_billing_unchanged(self) -> None:
        exc = _FakeError("insufficient balance")
        assert classify_failover_reason(exc) == FailoverReason.BILLING

    def test_auth_unchanged(self) -> None:
        exc = _FakeError("invalid api key", status_code=401)
        assert classify_failover_reason(exc) == FailoverReason.AUTH_PERMANENT

    def test_safety_block_unchanged(self) -> None:
        exc = _FakeError("content_policy_violation")
        assert classify_failover_reason(exc) == FailoverReason.SAFETY_BLOCK

    def test_timeout_unchanged(self) -> None:
        exc = _FakeError("connection timeout")
        assert classify_failover_reason(exc) == FailoverReason.TIMEOUT

    def test_overloaded_unchanged(self) -> None:
        exc = _FakeError("overloaded_error")
        assert classify_failover_reason(exc) == FailoverReason.OVERLOADED

    def test_413_still_context_overflow(self) -> None:
        exc = _FakeError("request too large", status_code=413)
        assert classify_failover_reason(exc) == FailoverReason.CONTEXT_OVERFLOW
