"""Tests for VisionFallbackProcessor — auxiliary vision text conversion."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from myrm_agent_harness.agent.config.llm import LLMConfig
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.vision_fallback_processor import (
    VisionFallbackProcessor,
    apply_vision_fallback_to_messages,
)


def _vision_cfg() -> LLMConfig:
    return LLMConfig(model="gpt-4o-mini", api_key="test-key")


def _img_message(text: str = "describe this") -> HumanMessage:
    return HumanMessage(
        content=[
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
        ]
    )


def _tool_with_image() -> ToolMessage:
    return ToolMessage(
        content=[
            {"type": "text", "text": "screenshot"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,def456"}},
        ],
        tool_call_id="call-1",
    )


class TestApplyVisionFallbackToMessages:
    @pytest.mark.asyncio
    async def test_skips_when_model_supports_vision(self) -> None:
        msgs = [_img_message()]
        converted = await apply_vision_fallback_to_messages(
            msgs,
            _vision_cfg(),
            supports_vision=True,
        )
        assert converted == 0
        assert msgs[0].content[1]["type"] == "image_url"

    @pytest.mark.asyncio
    async def test_skips_when_no_fallback_cfg(self) -> None:
        msgs = [_img_message()]
        converted = await apply_vision_fallback_to_messages(
            msgs,
            None,
            supports_vision=False,
        )
        assert converted == 0

    @pytest.mark.asyncio
    async def test_converts_base64_image_in_human_message(self) -> None:
        msgs = [_img_message("what is this diagram")]
        mock_engine = AsyncMock()
        mock_engine.describe_image_b64 = AsyncMock(return_value="error chart")

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.vision_fallback_processor.create_vision_fallback_engine",
            return_value=mock_engine,
        ):
            converted = await apply_vision_fallback_to_messages(
                msgs,
                _vision_cfg(),
                supports_vision=False,
            )

        assert converted == 1
        content = msgs[0].content
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "text"
        assert "[Image Analysis]" in str(content[1]["text"])
        call_args = mock_engine.describe_image_b64.await_args
        assert call_args.args == ("abc123", "image/png")
        prompt = call_args.kwargs["prompt"]
        assert "what is this diagram" in prompt
        assert "text-only assistant" in prompt

    @pytest.mark.asyncio
    async def test_converts_tool_message_with_adjacent_prompt(self) -> None:
        msgs = [HumanMessage(content="user question"), _tool_with_image()]
        mock_engine = AsyncMock()
        mock_engine.describe_image_b64 = AsyncMock(return_value="tool screenshot")

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.vision_fallback_processor.create_vision_fallback_engine",
            return_value=mock_engine,
        ):
            converted = await apply_vision_fallback_to_messages(
                msgs,
                _vision_cfg(),
                supports_vision=False,
            )

        assert converted == 1
        tool_content = msgs[1].content
        assert isinstance(tool_content, list)
        assert tool_content[1]["type"] == "text"
        call_args = mock_engine.describe_image_b64.await_args
        assert call_args.args == ("def456", "image/png")
        prompt = call_args.kwargs["prompt"]
        assert "user question" in prompt
        assert "text-only assistant" in prompt

    @pytest.mark.asyncio
    async def test_converts_api_media_url_via_resolver(self) -> None:
        msgs = [
            HumanMessage(
                content=[
                    {"type": "text", "text": "describe"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "/api/media/files/file_abc/content"},
                    },
                ]
            )
        ]
        mock_engine = AsyncMock()
        mock_engine.describe_image_b64 = AsyncMock(return_value="resolved image")
        reader = AsyncMock(return_value=b"pngbytes")

        with (
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.vision_fallback_processor.create_vision_fallback_engine",
                return_value=mock_engine,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.pipeline.processors.vision_fallback_processor.resolve_image_reference_to_data_url",
                new_callable=AsyncMock,
                return_value="data:image/png;base64,resolvedb64",
            ) as mock_resolve,
        ):
            converted = await apply_vision_fallback_to_messages(
                msgs,
                _vision_cfg(),
                supports_vision=False,
                file_content_reader=reader,
            )

        assert converted == 1
        mock_resolve.assert_awaited_once_with(
            "/api/media/files/file_abc/content",
            file_content_reader=reader,
        )
        call_args = mock_engine.describe_image_b64.await_args
        assert call_args.args == ("resolvedb64", "image/png")
        prompt = call_args.kwargs["prompt"]
        assert "describe" in prompt
        assert "text-only assistant" in prompt


class TestVisionFallbackProcessor:
    def test_resolve_file_content_reader_prefers_metadata_over_merged_context(
        self,
    ) -> None:
        """metadata is SSOT; merged_context must not carry file_content_reader (checkpoint pop)."""
        metadata_reader = lambda _fid: b"meta"  # noqa: E731
        merged_reader = lambda _fid: b"merged"  # noqa: E731
        ctx = ProcessorContext(
            messages=[],
            user_query="test",
            metadata={"file_content_reader": metadata_reader},
            merged_context={"file_content_reader": merged_reader},
        )
        resolved = VisionFallbackProcessor._resolve_file_content_reader(ctx)
        assert resolved is metadata_reader

    def test_resolve_file_content_reader_ignores_merged_context_only(self) -> None:
        merged_reader = lambda _fid: b"merged"  # noqa: E731
        ctx = ProcessorContext(
            messages=[],
            user_query="test",
            merged_context={"file_content_reader": merged_reader},
        )
        assert VisionFallbackProcessor._resolve_file_content_reader(ctx) is None

    @pytest.mark.asyncio
    async def test_should_process_when_text_only_and_cfg_present(self) -> None:
        proc = VisionFallbackProcessor()
        ctx = ProcessorContext(
            messages=[_img_message()],
            user_query="test",
            metadata={
                "supports_vision": False,
                "vision_fallback_model_cfg": _vision_cfg(),
            },
        )
        assert await proc.should_process(ctx) is True

    @pytest.mark.asyncio
    async def test_should_skip_when_vision_supported(self) -> None:
        proc = VisionFallbackProcessor()
        ctx = ProcessorContext(
            messages=[_img_message()],
            user_query="test",
            metadata={
                "supports_vision": True,
                "vision_fallback_model_cfg": _vision_cfg(),
            },
        )
        assert await proc.should_process(ctx) is False

    @pytest.mark.asyncio
    async def test_process_records_operation(self) -> None:
        proc = VisionFallbackProcessor()
        ctx = ProcessorContext(
            messages=[_img_message()],
            user_query="test",
            metadata={
                "supports_vision": False,
                "vision_fallback_model_cfg": _vision_cfg(),
            },
        )
        mock_engine = AsyncMock()
        mock_engine.describe_image_b64 = AsyncMock(return_value="ok")

        with patch(
            "myrm_agent_harness.agent.context_management.pipeline.processors.vision_fallback_processor.create_vision_fallback_engine",
            return_value=mock_engine,
        ):
            result = await proc.process(ctx)

        assert "vision_fallback" in result.operations
