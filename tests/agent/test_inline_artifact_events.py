from myrm_agent_harness.agent.streaming.types import AgentEventType

"""Tests for collect_inline_artifacts event generator."""

import pytest

from myrm_agent_harness.agent.artifacts import ArtifactType, InlineArtifactEvent, push_inline_artifact
from myrm_agent_harness.agent.artifacts.context import ArtifactContextManager
from myrm_agent_harness.agent.streaming.artifact_events import collect_inline_artifacts


async def _collect_all(message_id: str) -> list[dict[str, object]]:
    """Helper to collect all events from async generator."""
    events: list[dict[str, object]] = []
    async for event in collect_inline_artifacts(message_id):
        events.append(event)
    return events


class TestCollectInlineArtifacts:
    """Tests for collect_inline_artifacts() async generator."""

    @pytest.mark.asyncio
    async def test_no_context_yields_nothing(self):
        """Without ArtifactContext, yields zero events."""
        events = await _collect_all("msg_1")
        assert events == []

    @pytest.mark.asyncio
    async def test_empty_queue_yields_nothing(self):
        """With context but empty queue, yields zero events."""
        with ArtifactContextManager(message_id="msg_2"):
            events = await _collect_all("msg_2")
            assert events == []

    @pytest.mark.asyncio
    async def test_single_artifact_yields_one_event(self):
        with ArtifactContextManager(message_id="msg_3") as ctx:
            ctx.inline_artifact_queue.push(
                InlineArtifactEvent(
                    artifact_id="inline_abc",
                    filename="test.png",
                    artifact_type=ArtifactType.IMAGE,
                    content_type="image/png",
                    preview_url="https://example.com/test.png",
                )
            )

            events = await _collect_all("msg_3")
            assert len(events) == 1

            event = events[0]
            assert event["type"] == AgentEventType.ARTIFACTS.value
            assert event["messageId"] == "msg_3"

            data = event["data"]
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["id"] == "inline_abc"
            assert data[0]["filename"] == "test.png"
            assert data[0]["type"] == "image"
            assert data[0]["preview_url"] == "https://example.com/test.png"
            assert data[0]["download_url"] == "https://example.com/test.png"

    @pytest.mark.asyncio
    async def test_multiple_artifacts_batched(self):
        """Multiple artifacts are batched into one ARTIFACTS event."""
        with ArtifactContextManager(message_id="msg_4") as ctx:
            for i in range(3):
                ctx.inline_artifact_queue.push(
                    InlineArtifactEvent(
                        artifact_id=f"inline_{i}",
                        filename=f"img_{i}.png",
                        artifact_type=ArtifactType.IMAGE,
                        content_type="image/png",
                        preview_url=f"https://example.com/{i}.png",
                    )
                )

            events = await _collect_all("msg_4")
            assert len(events) == 1
            assert len(events[0]["data"]) == 3

    @pytest.mark.asyncio
    async def test_queue_drained_after_collect(self):
        """Queue is empty after collect_inline_artifacts runs."""
        with ArtifactContextManager(message_id="msg_5") as ctx:
            push_inline_artifact(filename="drain.png", preview_url="https://example.com/drain.png")
            assert ctx.inline_artifact_queue.has_pending_events()

            await _collect_all("msg_5")
            assert not ctx.inline_artifact_queue.has_pending_events()

    @pytest.mark.asyncio
    async def test_second_collect_yields_nothing(self):
        """After draining, second collect yields nothing."""
        with ArtifactContextManager(message_id="msg_6"):
            push_inline_artifact(filename="once.png", preview_url="https://example.com/once.png")
            first = await _collect_all("msg_6")
            assert len(first) == 1

            second = await _collect_all("msg_6")
            assert second == []

    @pytest.mark.asyncio
    async def test_push_then_collect_then_push_then_collect(self):
        """Simulates multiple tool calls pushing artifacts incrementally."""
        with ArtifactContextManager(message_id="msg_7"):
            push_inline_artifact(filename="a.png", preview_url="https://a.com/a.png")
            first = await _collect_all("msg_7")
            assert len(first) == 1
            assert first[0]["data"][0]["filename"] == "a.png"

            push_inline_artifact(filename="b.png", preview_url="https://b.com/b.png")
            second = await _collect_all("msg_7")
            assert len(second) == 1
            assert second[0]["data"][0]["filename"] == "b.png"

    @pytest.mark.asyncio
    async def test_event_data_format(self):
        """Verify all expected fields are present in the emitted data."""
        with ArtifactContextManager(message_id="msg_fmt") as ctx:
            ctx.inline_artifact_queue.push(
                InlineArtifactEvent(
                    artifact_id="inline_fmt",
                    filename="format.png",
                    artifact_type=ArtifactType.IMAGE,
                    content_type="image/jpeg",
                    preview_url="https://example.com/format.jpg",
                )
            )

            events = await _collect_all("msg_fmt")
            artifact_data = events[0]["data"][0]
            expected_keys = {"id", "filename", "type", "content_type", "size", "preview_url", "download_url"}
            assert set(artifact_data.keys()) == expected_keys
            assert artifact_data["size"] == 0
            assert artifact_data["content_type"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_non_image_artifact_type(self):
        """collect_inline_artifacts handles non-IMAGE artifact types."""
        with ArtifactContextManager(message_id="msg_svg") as ctx:
            ctx.inline_artifact_queue.push(
                InlineArtifactEvent(
                    artifact_id="inline_svg",
                    filename="diagram.svg",
                    artifact_type=ArtifactType.SVG,
                    content_type="image/svg+xml",
                    preview_url="https://example.com/diagram.svg",
                )
            )

            events = await _collect_all("msg_svg")
            assert events[0]["data"][0]["type"] == "svg"
