"""Tests for MediaFilterProcessor — proactive media filtering."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.media_filter import (
    CAPABILITY_REJECTS_MEDIA,
    MediaFilterProcessor,
)
from myrm_agent_harness.toolkits.llms.capability_learner import ModelCapabilityLearner


@pytest.fixture(autouse=True)
def _reset_learner():
    ModelCapabilityLearner._instance = None
    yield
    ModelCapabilityLearner._instance = None


def _make_context(
    messages: list,
    supports_vision: bool = True,
    model_name: str = "gpt-4o",
    is_resume: bool = False,
) -> ProcessorContext:
    return ProcessorContext(
        messages=messages,
        user_query="test",
        is_resume=is_resume,
        metadata={
            "supports_vision": supports_vision,
            "model_name": model_name,
        },
    )


def _img(text: str = "look") -> HumanMessage:
    return HumanMessage(
        content=[
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
        ]
    )


def _video() -> HumanMessage:
    return HumanMessage(
        content=[
            {"type": "text", "text": "watch this"},
            {
                "type": "video_url",
                "video_url": {"url": "https://example.com/video.mp4"},
            },
        ]
    )


def _audio() -> HumanMessage:
    return HumanMessage(
        content=[
            {"type": "text", "text": "listen"},
            {
                "type": "audio_url",
                "audio_url": {"url": "https://example.com/audio.mp3"},
            },
        ]
    )


def _text_only() -> HumanMessage:
    return HumanMessage(content="just text")


class TestShouldProcess:
    """Tests for the should_process decision logic."""

    @pytest.mark.asyncio
    async def test_process_always_runs_except_resume(self) -> None:
        proc = MediaFilterProcessor()
        ctx = _make_context([_img()], supports_vision=True)
        # Now always runs to check for historical media stripping
        assert await proc.should_process(ctx) is True

    @pytest.mark.asyncio
    async def test_process_when_vision_not_supported(self) -> None:
        proc = MediaFilterProcessor()
        ctx = _make_context([_img()], supports_vision=False)
        assert await proc.should_process(ctx) is True

    @pytest.mark.asyncio
    async def test_process_when_learner_says_rejects_media(self) -> None:
        from myrm_agent_harness.toolkits.llms.capability_learner import (
            get_capability_learner,
        )

        learner = get_capability_learner()
        learner.learn("gpt-4o-mini", CAPABILITY_REJECTS_MEDIA, True)

        proc = MediaFilterProcessor()
        ctx = _make_context([_img()], supports_vision=True, model_name="gpt-4o-mini")
        assert await proc.should_process(ctx) is True

        # Verify it actually strips everything
        result = await proc.process(ctx)
        content = result.messages[0].content
        assert isinstance(content, list)
        assert content[1]["type"] == "text"
        assert "does not support" in content[1]["text"].lower() or "removed" in content[1]["text"].lower()

    @pytest.mark.asyncio
    async def test_skip_when_resume(self) -> None:
        proc = MediaFilterProcessor()
        ctx = _make_context([_img()], supports_vision=False, is_resume=True)
        assert await proc.should_process(ctx) is False

    @pytest.mark.asyncio
    async def test_skip_when_hitl_session_active(self) -> None:
        proc = MediaFilterProcessor()
        ctx = _make_context([_img()], supports_vision=False)
        ctx.merged_context["hitl_session_active"] = True
        assert await proc.should_process(ctx) is False


class TestProcess:
    """Tests for media stripping logic."""

    @pytest.mark.asyncio
    async def test_strips_image_from_message(self) -> None:
        proc = MediaFilterProcessor()
        msg = _img()
        ctx = _make_context([msg], supports_vision=False)

        result = await proc.process(ctx)
        content = result.messages[0].content
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0] == {"type": "text", "text": "look"}
        assert (
            "removed" in content[1]["text"].lower()
            or "does not support" in content[1]["text"].lower()
        )

    @pytest.mark.asyncio
    async def test_strips_video(self) -> None:
        proc = MediaFilterProcessor()
        msg = _video()
        ctx = _make_context([msg], supports_vision=False)

        result = await proc.process(ctx)
        content = result.messages[0].content
        assert isinstance(content, list)
        assert content[1]["type"] == "text"
        assert "does not support" in content[1]["text"].lower()

    @pytest.mark.asyncio
    async def test_strips_audio(self) -> None:
        proc = MediaFilterProcessor()
        msg = _audio()
        ctx = _make_context([msg], supports_vision=False)

        result = await proc.process(ctx)
        content = result.messages[0].content
        assert isinstance(content, list)
        assert content[1]["type"] == "text"

    @pytest.mark.asyncio
    async def test_text_only_messages_unchanged(self) -> None:
        proc = MediaFilterProcessor()
        msg = _text_only()
        ctx = _make_context([msg], supports_vision=False)

        result = await proc.process(ctx)
        assert result.messages[0].content == "just text"

    @pytest.mark.asyncio
    async def test_mixed_messages(self) -> None:
        proc = MediaFilterProcessor()
        msgs = [_text_only(), _img("photo"), _text_only()]
        ctx = _make_context(msgs, supports_vision=False)

        result = await proc.process(ctx)
        assert result.messages[0].content == "just text"
        assert isinstance(result.messages[1].content, list)
        assert result.messages[2].content == "just text"

    @pytest.mark.asyncio
    async def test_historical_media_stripping(self) -> None:
        proc = MediaFilterProcessor()
        # 3 image messages
        msgs = [_img("photo1"), _img("photo2"), _img("photo3")]
        # model supports vision, so strip_all is False
        ctx = _make_context(msgs, supports_vision=True)

        result = await proc.process(ctx)

        # Default K=2, so photo3 and photo2 are kept, photo1 is stripped
        content_1 = result.messages[0].content
        assert isinstance(content_1, list)
        assert "removed" in content_1[1]["text"].lower() or "does not support" in content_1[1]["text"].lower() or "media stripped" in content_1[1]["text"].lower()

        content_2 = result.messages[1].content
        assert isinstance(content_2, list)
        assert content_2[1]["type"] == "image_url"

        content_3 = result.messages[2].content
        assert isinstance(content_3, list)
        assert content_3[1]["type"] == "image_url"

    @pytest.mark.asyncio
    async def test_historical_media_stripping_with_mixed_messages(self) -> None:
        proc = MediaFilterProcessor()
        # mixed messages
        msgs = [_text_only(), _img("photo1"), _text_only(), _img("photo2"), _text_only(), _img("photo3")]
        # model supports vision, so strip_all is False
        ctx = _make_context(msgs, supports_vision=True)

        result = await proc.process(ctx)

        # photo3 and photo2 are kept, photo1 is stripped
        content_1 = result.messages[1].content
        assert isinstance(content_1, list)
        assert "removed" in content_1[1]["text"].lower() or "does not support" in content_1[1]["text"].lower() or "media stripped" in content_1[1]["text"].lower()

        content_2 = result.messages[3].content
        assert isinstance(content_2, list)
        assert content_2[1]["type"] == "image_url"

        content_3 = result.messages[5].content
        assert isinstance(content_3, list)
        assert content_3[1]["type"] == "image_url"

    @pytest.mark.asyncio
    async def test_historical_media_stripping_under_limit(self) -> None:
        proc = MediaFilterProcessor()
        msgs = [_text_only(), _img("photo1")]
        ctx = _make_context(msgs, supports_vision=True)

        result = await proc.process(ctx)

        # photo1 is kept
        content_1 = result.messages[1].content
        assert isinstance(content_1, list)
        assert content_1[1]["type"] == "image_url"

    @pytest.mark.asyncio
    async def test_ai_message_with_image(self) -> None:
        proc = MediaFilterProcessor()
        ai_msg = AIMessage(
            content=[
                {"type": "text", "text": "here is what I see"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,xyz"},
                },
            ]
        )
        ctx = _make_context([ai_msg], supports_vision=False)

        result = await proc.process(ctx)
        content = result.messages[0].content
        assert isinstance(content, list)
        assert content[1]["type"] == "text"

    @pytest.mark.asyncio
    async def test_tokens_saved_counter(self) -> None:
        proc = MediaFilterProcessor()
        ctx = _make_context([_img(), _img("another")], supports_vision=False)

        result = await proc.process(ctx)
        assert result.tokens_saved >= 1000  # 500 * 2

    @pytest.mark.asyncio
    async def test_tool_message_with_image(self) -> None:
        proc = MediaFilterProcessor()
        tool_msg = ToolMessage(
            content=[
                {"type": "text", "text": "screenshot taken"},
                {"type": "image", "base64": "abc", "mime_type": "image/png"},
            ],
            tool_call_id="tc_1",
        )
        ctx = _make_context([tool_msg], supports_vision=False)

        result = await proc.process(ctx)
        content = result.messages[0].content
        assert isinstance(content, list)
        assert content[1]["type"] == "text"

    @pytest.mark.asyncio
    async def test_multiple_media_types_in_one_message(self) -> None:
        proc = MediaFilterProcessor()
        msg = HumanMessage(
            content=[
                {"type": "text", "text": "mixed"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,abc"},
                },
                {"type": "video_url", "video_url": {"url": "https://v.mp4"}},
                {"type": "audio_url", "audio_url": {"url": "https://a.mp3"}},
            ]
        )
        ctx = _make_context([msg], supports_vision=False)

        result = await proc.process(ctx)
        content = result.messages[0].content
        assert isinstance(content, list)
        assert len(content) == 4
        assert content[0] == {"type": "text", "text": "mixed"}
        for i in range(1, 4):
            assert content[i]["type"] == "text"

    @pytest.mark.asyncio
    async def test_processor_name(self) -> None:
        proc = MediaFilterProcessor()
        assert proc.name == "media_filter"


class TestPipelineIntegration:
    """Test MediaFilterProcessor within the pipeline."""

    @pytest.mark.asyncio
    async def test_included_in_default_pipeline(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.engine import (
            build_default_processors,
        )

        processors = build_default_processors()
        names = [p.name for p in processors]
        assert "media_filter" in names
        assert names.index("media_filter") < names.index("filter")

    @pytest.mark.asyncio
    async def test_pipeline_execution_with_text_only_model(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.engine import (
            ContextPipeline,
        )
        from myrm_agent_harness.agent.context_management.pipeline.processors.media_filter import (
            MediaFilterProcessor,
        )

        pipeline = ContextPipeline([MediaFilterProcessor()])
        msg = _img()
        ctx = _make_context([msg], supports_vision=False)

        result = await pipeline.process(ctx)
        assert "media_filter" in result.operations
        content = result.messages[0].content
        assert isinstance(content, list)
        assert content[1]["type"] == "text"
