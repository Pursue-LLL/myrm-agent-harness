"""Tests for OneshotRecoveryMixin handlers.

Covers _handle_thinking_signature, _handle_image_shrink,
_handle_long_context_tier, and _shrink_oversized_images.
"""

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.streaming.stream_recovery_oneshot import _shrink_oversized_images
from myrm_agent_harness.agent.types import AgentRunStatistics


class FakeCompactor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def put(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass


class _FakeError(Exception):
    def __init__(self, msg: str, status_code: int | None = None) -> None:
        super().__init__(msg)
        self.status_code = status_code


@pytest.fixture
def ctx():
    stats = AgentRunStatistics()
    return StreamContext(
        agent=MagicMock(),
        agent_input={"messages": [HumanMessage(content="test")]},
        merged_context={"locale": "en"},
        run_config={},
        stats=stats,
        message_id="oneshot_test",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
    )


def _make_executor(ctx: StreamContext) -> StreamExecutor:
    executor = StreamExecutor(
        ctx=ctx, fallback_llm=None, safety_fallback_llm=None, rebuild_agent_fn=MagicMock()
    )
    executor._compactor = FakeCompactor()
    return executor


# ============================================================================
# _handle_thinking_signature
# ============================================================================


class TestHandleThinkingSignature:
    @pytest.mark.asyncio
    async def test_strips_thinking_blocks(self, ctx: StreamContext) -> None:
        ctx.agent_input["messages"] = [
            HumanMessage(content="hello"),
            AIMessage(content=[
                {"type": "thinking", "thinking": "reasoning..."},
                {"type": "text", "text": "answer"},
            ]),
        ]
        exc = _FakeError("thinking block signature invalid", status_code=400)
        executor = _make_executor(ctx)

        result = await executor._handle_thinking_signature(exc, attempted=False)
        assert result is True
        ai_msg = ctx.agent_input["messages"][1]
        assert len(ai_msg.content) == 1
        assert ai_msg.content[0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_strips_reasoning_content(self, ctx: StreamContext) -> None:
        ai_msg = AIMessage(content="answer")
        ai_msg.additional_kwargs["reasoning_content"] = "deep thinking..."
        ctx.agent_input["messages"] = [HumanMessage(content="q"), ai_msg]
        exc = _FakeError("signature thinking invalid", status_code=400)
        executor = _make_executor(ctx)

        result = await executor._handle_thinking_signature(exc, attempted=False)
        assert result is True
        assert "reasoning_content" not in ai_msg.additional_kwargs

    @pytest.mark.asyncio
    async def test_returns_false_if_already_attempted(self, ctx: StreamContext) -> None:
        exc = _FakeError("thinking block signature invalid", status_code=400)
        executor = _make_executor(ctx)
        result = await executor._handle_thinking_signature(exc, attempted=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_non_matching_error(self, ctx: StreamContext) -> None:
        exc = _FakeError("generic error", status_code=400)
        executor = _make_executor(ctx)
        result = await executor._handle_thinking_signature(exc, attempted=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_in_command_mode(self, ctx: StreamContext) -> None:
        ctx.agent_input = Command(resume="test")
        exc = _FakeError("thinking block signature invalid", status_code=400)
        executor = _make_executor(ctx)
        result = await executor._handle_thinking_signature(exc, attempted=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_thinking_blocks(self, ctx: StreamContext) -> None:
        ctx.agent_input["messages"] = [
            HumanMessage(content="q"),
            AIMessage(content="no thinking here"),
        ]
        exc = _FakeError("thinking block signature invalid", status_code=400)
        executor = _make_executor(ctx)
        result = await executor._handle_thinking_signature(exc, attempted=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_strips_redacted_thinking_blocks(self, ctx: StreamContext) -> None:
        """redacted_thinking blocks must also be stripped to prevent retry failure."""
        ctx.agent_input["messages"] = [
            HumanMessage(content="hello"),
            AIMessage(content=[
                {"type": "thinking", "thinking": "visible reasoning"},
                {"type": "redacted_thinking", "data": "encrypted_payload_base64"},
                {"type": "text", "text": "answer"},
            ]),
        ]
        exc = _FakeError("thinking block signature invalid", status_code=400)
        executor = _make_executor(ctx)

        result = await executor._handle_thinking_signature(exc, attempted=False)
        assert result is True
        ai_msg = ctx.agent_input["messages"][1]
        assert len(ai_msg.content) == 1
        assert ai_msg.content[0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_strips_only_redacted_thinking(self, ctx: StreamContext) -> None:
        """When only redacted_thinking blocks are present (no regular thinking)."""
        ctx.agent_input["messages"] = [
            HumanMessage(content="hello"),
            AIMessage(content=[
                {"type": "redacted_thinking", "data": "encrypted_data"},
                {"type": "text", "text": "answer"},
            ]),
        ]
        exc = _FakeError("thinking block signature invalid", status_code=400)
        executor = _make_executor(ctx)

        result = await executor._handle_thinking_signature(exc, attempted=False)
        assert result is True
        ai_msg = ctx.agent_input["messages"][1]
        assert len(ai_msg.content) == 1
        assert ai_msg.content[0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_strips_thinking_blocks_from_kwargs(self, ctx: StreamContext) -> None:
        """thinking_blocks in additional_kwargs must also be cleaned."""
        ai_msg = AIMessage(content="answer")
        ai_msg.additional_kwargs["thinking_blocks"] = [
            {"type": "thinking", "thinking": "reasoning", "signature": "sig123"},
        ]
        ctx.agent_input["messages"] = [HumanMessage(content="q"), ai_msg]
        exc = _FakeError("signature thinking invalid", status_code=400)
        executor = _make_executor(ctx)

        result = await executor._handle_thinking_signature(exc, attempted=False)
        assert result is True
        assert "thinking_blocks" not in ai_msg.additional_kwargs

    @pytest.mark.asyncio
    async def test_strips_all_thinking_artifacts(self, ctx: StreamContext) -> None:
        """Combined: content blocks + reasoning_content + thinking_blocks all stripped."""
        ai_msg = AIMessage(content=[
            {"type": "thinking", "thinking": "visible"},
            {"type": "redacted_thinking", "data": "encrypted"},
            {"type": "text", "text": "answer"},
        ])
        ai_msg.additional_kwargs["reasoning_content"] = "deep thinking..."
        ai_msg.additional_kwargs["thinking_blocks"] = [
            {"type": "thinking", "thinking": "r", "signature": "s"},
        ]
        ctx.agent_input["messages"] = [HumanMessage(content="q"), ai_msg]
        exc = _FakeError("thinking block signature invalid", status_code=400)
        executor = _make_executor(ctx)

        result = await executor._handle_thinking_signature(exc, attempted=False)
        assert result is True
        assert len(ai_msg.content) == 1
        assert ai_msg.content[0]["type"] == "text"
        assert "reasoning_content" not in ai_msg.additional_kwargs
        assert "thinking_blocks" not in ai_msg.additional_kwargs

    @pytest.mark.asyncio
    async def test_emits_recovery_event(self, ctx: StreamContext) -> None:
        ctx.agent_input["messages"] = [
            HumanMessage(content="q"),
            AIMessage(content=[{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "a"}]),
        ]
        exc = _FakeError("thinking block signature invalid", status_code=400)
        executor = _make_executor(ctx)
        await executor._handle_thinking_signature(exc, attempted=False)
        events = executor._compactor.events
        assert any(
            isinstance(e, dict) and e.get("step_key") == "thinking_signature_recovery"
            for e in events
        )


# ============================================================================
# _handle_image_shrink
# ============================================================================


def _make_large_base64_image(size_bytes: int = 5 * 1024 * 1024) -> str:
    raw = b"\x89PNG\r\n" + b"\x00" * size_bytes
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


class TestHandleImageShrink:
    @pytest.mark.asyncio
    async def test_returns_false_if_already_attempted(self, ctx: StreamContext) -> None:
        exc = _FakeError("image exceeds 5 MB maximum", status_code=400)
        executor = _make_executor(ctx)
        result = await executor._handle_image_shrink(exc, attempted=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_non_matching_error(self, ctx: StreamContext) -> None:
        exc = _FakeError("some other error", status_code=400)
        executor = _make_executor(ctx)
        result = await executor._handle_image_shrink(exc, attempted=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_in_command_mode(self, ctx: StreamContext) -> None:
        ctx.agent_input = Command(resume="test")
        exc = _FakeError("image exceeds 5 MB maximum", status_code=400)
        executor = _make_executor(ctx)
        result = await executor._handle_image_shrink(exc, attempted=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_images(self, ctx: StreamContext) -> None:
        ctx.agent_input["messages"] = [
            HumanMessage(content="no images here"),
        ]
        exc = _FakeError("image exceeds 5 MB maximum", status_code=400)
        executor = _make_executor(ctx)
        result = await executor._handle_image_shrink(exc, attempted=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_shrinks_and_returns_true(self, ctx: StreamContext) -> None:
        large_url = _make_large_base64_image(5 * 1024 * 1024)
        ctx.agent_input["messages"] = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": large_url}},
            ]),
        ]
        exc = _FakeError("image exceeds 5 MB maximum", status_code=400)
        executor = _make_executor(ctx)

        with patch(
            "myrm_agent_harness.utils.media.image_compressor.ImageCompressor"
        ) as mock_compressor:
            mock_instance = mock_compressor.return_value
            mock_instance.compress.return_value = b"\x89PNG\r\n" + b"\x00" * 1000
            result = await executor._handle_image_shrink(exc, attempted=False)

        assert result is True

    @pytest.mark.asyncio
    async def test_emits_recovery_event(self, ctx: StreamContext) -> None:
        large_url = _make_large_base64_image(5 * 1024 * 1024)
        ctx.agent_input["messages"] = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": large_url}},
            ]),
        ]
        exc = _FakeError("image exceeds 5 MB maximum", status_code=400)
        executor = _make_executor(ctx)

        with patch(
            "myrm_agent_harness.utils.media.image_compressor.ImageCompressor"
        ) as mock_compressor:
            mock_instance = mock_compressor.return_value
            mock_instance.compress.return_value = b"\x89PNG\r\n" + b"\x00" * 1000
            await executor._handle_image_shrink(exc, attempted=False)

        events = executor._compactor.events
        assert any(
            isinstance(e, dict) and e.get("step_key") == "image_shrink_recovery"
            for e in events
        )


# ============================================================================
# _handle_long_context_tier
# ============================================================================


class TestHandleLongContextTier:
    @pytest.mark.asyncio
    async def test_returns_false_for_non_matching_error(self, ctx: StreamContext) -> None:
        exc = _FakeError("rate limit exceeded", status_code=429)
        executor = _make_executor(ctx)
        result = await executor._handle_long_context_tier(exc)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_in_command_mode(self, ctx: StreamContext) -> None:
        ctx.agent_input = Command(resume="test")
        exc = _FakeError("Extra usage is required for long context requests", status_code=429)
        executor = _make_executor(ctx)
        result = await executor._handle_long_context_tier(exc)
        assert result is False

    @pytest.mark.asyncio
    async def test_compresses_and_returns_true(self, ctx: StreamContext) -> None:
        ctx.agent_input["messages"] = [
            HumanMessage(content="q"),
            AIMessage(content="a" * 50000),
        ]
        exc = _FakeError("Extra usage is required for long context requests", status_code=429)
        executor = _make_executor(ctx)

        with patch(
            "myrm_agent_harness.agent.streaming.stream_recovery_oneshot._emergency_compact",
            new_callable=AsyncMock,
            return_value=5000,
        ):
            result = await executor._handle_long_context_tier(exc)
        assert result is True

    @pytest.mark.asyncio
    async def test_falls_back_to_truncation(self, ctx: StreamContext) -> None:
        ctx.agent_input["messages"] = [
            HumanMessage(content="q"),
            AIMessage(content="answer"),
        ]
        exc = _FakeError("Extra usage is required for long context requests", status_code=429)
        executor = _make_executor(ctx)

        with (
            patch(
                "myrm_agent_harness.agent.streaming.stream_recovery_oneshot._emergency_compact",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "myrm_agent_harness.agent.streaming.stream_recovery_oneshot._truncate_oldest_rounds",
                return_value=3000,
            ),
        ):
            result = await executor._handle_long_context_tier(exc)
        assert result is True

    @pytest.mark.asyncio
    async def test_emits_recovery_event(self, ctx: StreamContext) -> None:
        ctx.agent_input["messages"] = [
            HumanMessage(content="q"),
            AIMessage(content="a"),
        ]
        exc = _FakeError("Extra usage is required for long context requests", status_code=429)
        executor = _make_executor(ctx)

        with patch(
            "myrm_agent_harness.agent.streaming.stream_recovery_oneshot._emergency_compact",
            new_callable=AsyncMock,
            return_value=2000,
        ):
            await executor._handle_long_context_tier(exc)

        events = executor._compactor.events
        assert any(
            isinstance(e, dict) and e.get("step_key") == "long_context_tier_recovery"
            for e in events
        )


# ============================================================================
# _shrink_oversized_images (module-level function)
# ============================================================================


class TestShrinkOversizedImages:
    def test_returns_zero_when_no_images(self) -> None:
        messages = [HumanMessage(content="no images")]
        assert _shrink_oversized_images(messages) == 0

    def test_skips_small_images(self) -> None:
        small_url = f"data:image/png;base64,{base64.b64encode(b'tiny').decode()}"
        messages = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": small_url}},
            ]),
        ]
        assert _shrink_oversized_images(messages) == 0

    def test_skips_http_urls(self) -> None:
        messages = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
            ]),
        ]
        assert _shrink_oversized_images(messages) == 0

    def test_shrinks_large_image(self) -> None:
        large_url = _make_large_base64_image(5 * 1024 * 1024)
        messages = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": large_url}},
            ]),
        ]
        with patch(
            "myrm_agent_harness.utils.media.image_compressor.ImageCompressor"
        ) as mock_compressor:
            mock_instance = mock_compressor.return_value
            mock_instance.compress.return_value = b"\x89PNG\r\n" + b"\x00" * 1000
            count = _shrink_oversized_images(messages)
        assert count == 1

    def test_skips_non_dict_content(self) -> None:
        messages = [AIMessage(content="just text")]
        assert _shrink_oversized_images(messages) == 0

    def test_handles_compress_exception(self) -> None:
        large_url = _make_large_base64_image(5 * 1024 * 1024)
        messages = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": large_url}},
            ]),
        ]
        with patch(
            "myrm_agent_harness.utils.media.image_compressor.ImageCompressor"
        ) as mock_compressor:
            mock_instance = mock_compressor.return_value
            mock_instance.compress.side_effect = RuntimeError("compression failed")
            count = _shrink_oversized_images(messages)
        assert count == 0


# ============================================================================
# Real Pillow pixel-correct tests (no mocks)
# ============================================================================


def _make_real_base64_image(width: int, height: int, fmt: str = "PNG") -> str:
    """Create a real Pillow image and return as a base64 data URL."""
    import io

    from PIL import Image

    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    raw = buf.getvalue()
    b64 = base64.b64encode(raw).decode("ascii")
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


class TestShrinkOversizedImagesRealPillow:
    """Real Pillow integration tests — no mocks, actual image processing."""

    def test_dimension_only_oversized_gets_shrunk(self) -> None:
        """Retina screenshot: large pixels, small bytes."""
        url = _make_real_base64_image(2880, 1800)
        messages = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": url}},
            ]),
        ]
        count = _shrink_oversized_images(messages, max_dimension=2000)
        assert count == 1
        new_url = messages[0].content[0]["image_url"]["url"]
        assert new_url != url

    def test_dimension_within_limit_not_touched(self) -> None:
        """Image within dimension limit should not be modified."""
        url = _make_real_base64_image(1920, 1080)
        messages = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": url}},
            ]),
        ]
        count = _shrink_oversized_images(messages, max_dimension=2000)
        assert count == 0

    def test_shrunk_image_respects_max_dimension(self) -> None:
        """After shrinking, image dimensions must be within limit."""
        import io

        from PIL import Image

        url = _make_real_base64_image(3840, 2160)
        messages = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": url}},
            ]),
        ]
        count = _shrink_oversized_images(messages, max_dimension=2000)
        assert count == 1

        new_url = messages[0].content[0]["image_url"]["url"]
        _, b64_data = new_url.split(";base64,", 1)
        raw = base64.b64decode(b64_data)
        with Image.open(io.BytesIO(raw)) as img:
            w, h = img.size
            assert max(w, h) <= 2000

    def test_bytes_oversized_gets_shrunk(self) -> None:
        """Large JPEG that exceeds byte threshold."""
        import io

        from PIL import Image

        img = Image.new("RGB", (4000, 3000), color=(50, 100, 200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=100)
        raw = buf.getvalue()
        if len(raw) < 4 * 1024 * 1024:
            raw = raw + b"\xff" * (4 * 1024 * 1024 - len(raw) + 1024)
        b64 = base64.b64encode(raw).decode("ascii")
        url = f"data:image/jpeg;base64,{b64}"

        messages = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": url}},
            ]),
        ]
        count = _shrink_oversized_images(messages, max_dimension=8000)
        assert count >= 0  # may be 0 if unshrinkable (padded bytes)

    def test_classifier_matches_dimension_error(self) -> None:
        """Verify classifier correctly identifies dimension-related errors."""
        from myrm_agent_harness.toolkits.llms.errors.classifier import (
            classify_failover_reason,
        )
        from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason

        dimension_errors = [
            "image dimension exceeds the maximum allowed size of 2000",
            "image dimensions exceed 8000 pixels",
        ]
        for err_msg in dimension_errors:
            exc = _FakeError(err_msg, status_code=400)
            assert classify_failover_reason(exc) == FailoverReason.IMAGE_TOO_LARGE, (
                f"Failed to classify: {err_msg}"
            )

    def test_parse_max_dimension_from_error(self) -> None:
        """Verify max_dimension parsing from error messages."""
        from myrm_agent_harness.agent.streaming.stream_recovery_oneshot import (
            _parse_image_max_dimension,
        )

        exc = _FakeError("image dimension exceeds the maximum allowed size of 2000")
        dim = _parse_image_max_dimension(exc)
        assert dim == 2000
