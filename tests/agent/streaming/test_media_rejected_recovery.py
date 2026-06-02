"""Tests for _handle_media_rejected oneshot recovery handler."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.streaming.stream_recovery_oneshot import (
    OneshotRecoveryMixin,
    _resolve_model_name_from_ctx,
    _strip_all_media_from_messages,
)
from myrm_agent_harness.toolkits.llms.capability_learner import ModelCapabilityLearner


@dataclass
class _FakeStreamContext:
    agent_input: dict[str, object] = field(default_factory=dict)
    message_id: str = "test-msg-id"
    merged_context: dict[str, object] = field(default_factory=dict)
    llm_info: dict[str, str | None] | None = None


class _FakeCompactor:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def put(self, event: dict) -> None:
        self.events.append(event)


class _FakeError(Exception):
    def __init__(self, msg: str, status_code: int | None = None) -> None:
        super().__init__(msg)
        self.status_code = status_code


class _FakeRecovery(OneshotRecoveryMixin):
    def __init__(self, ctx: _FakeStreamContext, compactor: _FakeCompactor) -> None:
        self._ctx = ctx  # type: ignore[assignment]
        self._compactor = compactor  # type: ignore[assignment]
        self.streaming_final_answer = True


@pytest.fixture(autouse=True)
def _reset_learner():
    ModelCapabilityLearner._instance = None
    yield
    ModelCapabilityLearner._instance = None


def _make_messages_with_image() -> list:
    return [
        HumanMessage(
            content=[
                {"type": "text", "text": "look at this"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,abc123"},
                },
            ]
        ),
        AIMessage(content="I see an image"),
        HumanMessage(content="what else?"),
    ]


def _make_messages_with_video() -> list:
    return [
        HumanMessage(
            content=[
                {"type": "text", "text": "watch this"},
                {
                    "type": "video_url",
                    "video_url": {"url": "https://example.com/v.mp4"},
                },
            ]
        ),
    ]


class TestHandleMediaRejected:
    """Test _handle_media_rejected oneshot handler."""

    @pytest.mark.asyncio
    async def test_handles_media_rejected_error(self) -> None:
        messages = _make_messages_with_image()
        ctx = _FakeStreamContext(
            agent_input={"messages": messages},
            llm_info={"model_name": "gpt-4o-text", "base_url": None},
        )
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("This model does not support image input", status_code=400)
        result = await recovery._handle_media_rejected(exc, attempted=False)

        assert result is True
        content = messages[0].content
        assert isinstance(content, list)
        assert content[1]["type"] == "text"
        assert "does not support" in content[1]["text"].lower()
        assert recovery.streaming_final_answer is False

    @pytest.mark.asyncio
    async def test_skips_if_already_attempted(self) -> None:
        ctx = _FakeStreamContext(agent_input={"messages": _make_messages_with_image()})
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("does not support image input", status_code=400)
        result = await recovery._handle_media_rejected(exc, attempted=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_skips_non_media_rejected_error(self) -> None:
        ctx = _FakeStreamContext(agent_input={"messages": _make_messages_with_image()})
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("rate limit exceeded", status_code=429)
        result = await recovery._handle_media_rejected(exc, attempted=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_learns_model_capability(self) -> None:
        from myrm_agent_harness.toolkits.llms.capability_learner import (
            get_capability_learner,
        )

        messages = _make_messages_with_image()
        ctx = _FakeStreamContext(
            agent_input={"messages": messages},
            llm_info={"model_name": "my-text-model", "base_url": None},
        )
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("does not support image input", status_code=400)
        await recovery._handle_media_rejected(exc, attempted=False)

        learner = get_capability_learner()
        assert learner.get("my-text-model", "rejects_media") is True

    @pytest.mark.asyncio
    async def test_emits_recovery_event(self) -> None:
        messages = _make_messages_with_image()
        ctx = _FakeStreamContext(agent_input={"messages": messages})
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("does not support image input", status_code=400)
        await recovery._handle_media_rejected(exc, attempted=False)

        assert len(compactor.events) == 1
        event = compactor.events[0]
        assert event["step_key"] == "media_rejected_recovery"

    @pytest.mark.asyncio
    async def test_handles_video_content(self) -> None:
        messages = _make_messages_with_video()
        ctx = _FakeStreamContext(agent_input={"messages": messages})
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("does not support media input", status_code=400)
        result = await recovery._handle_media_rejected(exc, attempted=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_media_returns_false(self) -> None:
        messages = [HumanMessage(content="just text")]
        ctx = _FakeStreamContext(agent_input={"messages": messages})
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("does not support image input", status_code=400)
        result = await recovery._handle_media_rejected(exc, attempted=False)
        assert result is False


class TestStripAllMediaFromMessages:
    """Test the helper _strip_all_media_from_messages."""

    def test_strips_images(self) -> None:
        messages = _make_messages_with_image()
        count = _strip_all_media_from_messages(messages)
        assert count == 1

    def test_strips_video(self) -> None:
        messages = _make_messages_with_video()
        count = _strip_all_media_from_messages(messages)
        assert count == 1

    def test_no_media_returns_zero(self) -> None:
        messages = [HumanMessage(content="text only")]
        count = _strip_all_media_from_messages(messages)
        assert count == 0

    def test_string_content_ignored(self) -> None:
        messages = [HumanMessage(content="string content")]
        count = _strip_all_media_from_messages(messages)
        assert count == 0

    def test_multiple_messages_counted(self) -> None:
        messages = [
            HumanMessage(
                content=[
                    {"type": "image_url", "image_url": {"url": "base64..."}},
                ]
            ),
            HumanMessage(
                content=[
                    {"type": "video_url", "video_url": {"url": "https://v.mp4"}},
                ]
            ),
            HumanMessage(content="text"),
        ]
        count = _strip_all_media_from_messages(messages)
        assert count == 2


class TestResolveModelNameFromCtx:
    def test_prefers_llm_info(self) -> None:
        ctx = _FakeStreamContext(
            llm_info={"model_name": "from-llm", "base_url": None},
            merged_context={"model_name": "from-merged"},
        )
        assert _resolve_model_name_from_ctx(ctx) == "from-llm"

    def test_falls_back_to_merged_context(self) -> None:
        ctx = _FakeStreamContext(merged_context={"model_name": "from-merged"})
        assert _resolve_model_name_from_ctx(ctx) == "from-merged"

    def test_returns_none_when_missing(self) -> None:
        ctx = _FakeStreamContext()
        assert _resolve_model_name_from_ctx(ctx) is None


class TestLearnWithoutModelName:
    @pytest.mark.asyncio
    async def test_no_learn_when_llm_info_missing(self) -> None:
        from myrm_agent_harness.toolkits.llms.capability_learner import (
            get_capability_learner,
        )

        messages = _make_messages_with_image()
        ctx = _FakeStreamContext(agent_input={"messages": messages})
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("does not support image input", status_code=400)
        result = await recovery._handle_media_rejected(exc, attempted=False)
        assert result is True

        learner = get_capability_learner()
        assert learner.size() == 0
