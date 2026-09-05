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

    def test_classify_failover_reason_413_with_payload_too_large(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import (
            FailoverReason,
            classify_failover_reason,
        )
        exc = _FakeError("Request entity too large", status_code=413)
        assert classify_failover_reason(exc) == FailoverReason.IMAGE_TOO_LARGE

    def test_classify_failover_reason_400_with_payload_too_large(self) -> None:
        from myrm_agent_harness.toolkits.llms.errors.classifier import (
            FailoverReason,
            classify_failover_reason,
        )
        exc = _FakeError("400 Bad Request: request body too large", status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.IMAGE_TOO_LARGE


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
        # Turn 1 should be converted to text summary (or downsampled)
        # Latest turn (turn 3) should still be an image
        assert message_dicts[4]["content"][0]["type"] == "image_url"

    def test_downsamples_real_image_preserving_multimodal(self) -> None:
        import io
        import os

        from PIL import Image

        # Create a real 400x400 image with random noise so PNG deflate cannot trivially compress it
        random_bytes = os.urandom(400 * 400 * 3)
        img = Image.frombytes("RGB", (400, 400), random_bytes)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        real_url = f"data:image/png;base64,{b64}"

        message_dicts = [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": real_url}}]}
        ]

        # Target 250KB: uncompressed noise PNG is ~480KB, downsampled WebP is ~100-150KB
        evicted = CumulativeImageBudgetGovernor.emergency_evict_from_message_dicts(
            message_dicts, target_bytes=250 * 1024
        )

        assert evicted >= 1
        # Should still be image_url because Stage 1 downsamples to WebP and reaches target_bytes!
        assert message_dicts[0]["content"][0]["type"] == "image_url"
        new_url = message_dicts[0]["content"][0]["image_url"]["url"]
        assert "image/webp" in new_url

    def test_emergency_evict_base_messages(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        img1 = _make_dummy_data_url(2000)
        img2 = _make_dummy_data_url(2000)

        messages = [
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": img1}}]),
            AIMessage(content="Reviewed."),
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": img2}}]),
        ]

        evicted = CumulativeImageBudgetGovernor.emergency_evict(
            messages, target_bytes=2 * 1024 * 1024
        )
        assert evicted >= 1
        # Historical message textified
        assert messages[0].content[0]["type"] == "text"
        assert "[Historical Image omitted" in messages[0].content[0]["text"]
        # Focus message preserved as image
        assert messages[2].content[0]["type"] == "image_url"


async def _async_iter(items: list[object]) -> object:
    for item in items:
        yield item


class TestChatLiteLLMPayloadRecovery:
    """Test ChatLiteLLM in-place retry recovery when payload overflow occurs."""

    @pytest.mark.asyncio
    async def test_async_stream_payload_overflow_recovers(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from langchain_core.messages import HumanMessage

        from myrm_agent_harness.toolkits.llms.core.llm import ChatLiteLLM

        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        calls = {"count": 0}

        img1 = _make_dummy_data_url(2000)
        img2 = _make_dummy_data_url(2000)

        async def _flaky(messages: object, **kwargs: object) -> object:
            calls["count"] += 1
            if calls["count"] == 1:
                raise _FakeError("413 Request Entity Too Large", status_code=413)
            return _async_iter(
                [
                    {"choices": [{"delta": {"role": "assistant", "content": "streaming recovered"}}]},
                    {"choices": [{"delta": {"content": None}, "finish_reason": "stop"}]},
                ]
            )

        model.client.acreate = AsyncMock(side_effect=_flaky)
        model.empty_retry_max_attempts = 2
        model.empty_retry_delay = 0.01

        messages = [
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": img1}}]),
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": img2}}]),
        ]

        collected = []
        async for chunk in model._astream(messages):
            collected.append(chunk)

        assert calls["count"] == 2
        assert any("streaming recovered" in str(c.message.content) for c in collected)
        # Historical message in messages was emergency evicted
        assert messages[0].content[0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_agenerate_payload_overflow_recovers(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from langchain_core.messages import HumanMessage

        from myrm_agent_harness.toolkits.llms.core.llm import ChatLiteLLM

        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        calls = {"count": 0}

        img1 = _make_dummy_data_url(2000)
        img2 = _make_dummy_data_url(2000)

        async def _flaky_agenerate(messages: object, **kwargs: object) -> object:
            calls["count"] += 1
            if calls["count"] == 1:
                raise _FakeError("400 Bad Request: payload size exceeds 10MB", status_code=400)
            return {
                "choices": [{"message": {"role": "assistant", "content": "agenerate recovered"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }

        model.client.acreate = AsyncMock(side_effect=_flaky_agenerate)
        model.empty_retry_max_attempts = 2
        model.empty_retry_delay = 0.01

        messages = [
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": img1}}]),
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": img2}}]),
        ]

        result = await model._agenerate(messages)
        assert calls["count"] == 2
        assert result.generations[0].message.content == "agenerate recovered"
        # Historical message was evicted
        assert messages[0].content[0]["type"] == "text"

    def test_sync_stream_payload_overflow_recovers(self) -> None:
        from unittest.mock import MagicMock
        from langchain_core.messages import HumanMessage
        from myrm_agent_harness.toolkits.llms.core.llm import ChatLiteLLM

        model = ChatLiteLLM(model="openai/test-model")
        model.client = MagicMock()
        calls = {"count": 0}

        img1 = _make_dummy_data_url(2000)
        img2 = _make_dummy_data_url(2000)

        def _flaky_stream(messages: object, **kwargs: object) -> object:
            calls["count"] += 1
            if calls["count"] == 1:
                raise _FakeError("413 Request Entity Too Large", status_code=413)
            return iter(
                [
                    {"choices": [{"delta": {"role": "assistant", "content": "sync stream recovered"}}]},
                    {"choices": [{"delta": {"content": None}, "finish_reason": "stop"}]},
                ]
            )

        model.client.completion = MagicMock(side_effect=_flaky_stream)
        model.empty_retry_max_attempts = 2
        model.empty_retry_delay = 0.01

        messages = [
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": img1}}]),
            HumanMessage(content=[{"type": "image_url", "image_url": {"url": img2}}]),
        ]

        collected = []
        for chunk in model._stream(messages):
            collected.append(chunk)

        assert calls["count"] == 2
        assert any("sync stream recovered" in str(c.message.content) for c in collected)
        assert messages[0].content[0]["type"] == "text"


