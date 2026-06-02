"""Tests for MEDIA_REJECTED error classification."""

from __future__ import annotations

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


class TestMediaRejectedClassification:
    """MEDIA_REJECTED error type classification."""

    @pytest.mark.parametrize(
        "msg",
        [
            "This model does not support image input",
            "model does not support vision capabilities",
            "does not support multimodal content",
            "does not support media input",
            "Image input not supported for this model",
            "vision is not available for this model",
            "multimodal input unsupported",
            "Cannot process image content with this model",
            "cannot process media input",
            "model does not have vision capabilities",
            "content type image not supported",
            "invalid content type: image_url",
        ],
    )
    def test_classify_media_rejected(self, msg: str) -> None:
        exc = _FakeError(msg, status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.MEDIA_REJECTED

    def test_media_rejected_is_transient(self) -> None:
        assert (
            FailoverReason.MEDIA_REJECTED.recoverability
            == RecoverabilityLevel.TRANSIENT
        )

    def test_media_rejected_not_failoverable(self) -> None:
        assert not FailoverReason.MEDIA_REJECTED.is_failoverable

    def test_media_rejected_probe_policy_disabled(self) -> None:
        policy = get_probe_policy(FailoverReason.MEDIA_REJECTED)
        assert not policy.enabled

    def test_media_rejected_maps_to_format_error_kind(self) -> None:
        exc = _FakeError("does not support image input", status_code=400)
        assert classify_error(exc) == ErrorKind.FORMAT_ERROR

    def test_image_too_large_priority_over_media_rejected(self) -> None:
        exc = _FakeError("image exceeds 5 MB maximum", status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.IMAGE_TOO_LARGE

    def test_generic_400_not_media_rejected(self) -> None:
        exc = _FakeError("something went wrong", status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.FORMAT_ERROR

    def test_existing_types_not_broken(self) -> None:
        assert (
            classify_failover_reason(_FakeError("rate limit exceeded", status_code=429))
            == FailoverReason.RATE_LIMIT
        )
        assert (
            classify_failover_reason(_FakeError("insufficient balance"))
            == FailoverReason.BILLING
        )
        assert (
            classify_failover_reason(_FakeError("context_length_exceeded"))
            == FailoverReason.CONTEXT_OVERFLOW
        )
