"""Tests for multimodal payload overflow classification and emergency eviction recovery."""

from __future__ import annotations

import base64
import pytest

from myrm_agent_harness.agent.context_management.pipeline.processors.media_budget_governor import (
    CumulativeImageBudgetGovernor,
)
from myrm_agent_harness.toolkits.llms.errors.classifier import (
    is_payload_overflow,
)


class _FakeError(Exception):
    def __init__(self, msg: str, status_code: int | None = None) -> None:
        super().__init__(msg)
        self.status_code = status_code


def _make_dummy_data_url(size_kb: int) -> str:
    raw = b"A" * (size_kb * 1024)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


class TestPayloadOverflowClassifier:
    """Test is_payload_overflow detection across status codes and error messages."""

    def test_http_413_is_always_payload_overflow(self) -> None:
        exc = _FakeError("Request entity too large", status_code=413)
        assert is_payload_overflow(exc) is True

    @pytest.mark.parametrize(
        "msg",
        [
            "Payload Too Large",
            "Request Entity Too Large",
            "request body too large",
            "413 client_max_body_size exceeded",
            "exceeded the maximum request size allowed",
            "request size exceeds maximum 15MB limit",
            "image exceeds 10MB per-image limit",
            "image size exceeds maximum allowed size",
        ],
    )
    def test_http_400_with_payload_or_image_overflow_message(self, msg: str) -> None:
        exc = _FakeError(msg, status_code=400)
        assert is_payload_overflow(exc) is True

    def test_generic_400_is_not_payload_overflow(self) -> None:
        exc = _FakeError("Invalid JSON body", status_code=400)
        assert is_payload_overflow(exc) is False


class TestEmergencyEvictFromMessageDicts:
    """Test in-flight message_dicts emergency eviction for payload recovery."""

    def test_no_eviction_when_under_budget(self) -> None:
        small_url = _make_dummy_data_url(100)  # 100KB
        message_dicts = [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": small_url}}]}
        ]
        evicted = CumulativeImageBudgetGovernor.emergency_evict_from_message_dicts(
            message_dicts, target_bytes=1024 * 1024
        )
        assert evicted == 0
        assert message_dicts[0]["content"][0]["type"] == "image_url"

    def test_evicts_old_turn_first_protecting_focus_turn(self) -> None:
        img_turn1 = _make_dummy_data_url(2000)  # ~2MB
        img_turn2 = _make_dummy_data_url(3000)  # ~3MB
        img_turn3 = _make_dummy_data_url(2000)  # ~2MB (focus)

        message_dicts = [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": img_turn1}}]},
            {"role": "assistant", "content": "I see the first UI."},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": img_turn2}}]},
            {"role": "assistant", "content": "I see the second UI."},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": img_turn3}}]},
        ]

        # Total is ~7MB, target is 3MB
        evicted = CumulativeImageBudgetGovernor.emergency_evict_from_message_dicts(
            message_dicts, target_bytes=3 * 1024 * 1024
        )

        assert evicted >= 1
        # Turn 1 should be converted to text summary
        assert message_dicts[0]["content"][0]["type"] == "text"
        assert "[Historical Image omitted" in message_dicts[0]["content"][0]["text"]
        # Latest turn (turn 3) should still be an image
        assert message_dicts[4]["content"][0]["type"] == "image_url"
