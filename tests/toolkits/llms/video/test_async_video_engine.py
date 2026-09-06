"""Tests for async video enqueue adapter and video_engine URL extraction.

[POS]
Tests for AsyncVideoGenerationTools and VideoGenerationTools URL-to-extra_params chain.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from myrm_agent_harness.toolkits.llms.video.async_video_engine import AsyncVideoGenerationTools
from myrm_agent_harness.toolkits.llms.video.models import VideoGenerationConfig, VideoResult
from myrm_agent_harness.toolkits.tasks import SQLiteTaskStore, TaskStatus


@pytest.mark.asyncio
async def test_async_video_engine_enqueues_task_snapshot(tmp_path: Path) -> None:
    store = SQLiteTaskStore(db_path=str(tmp_path / "video-tasks.db"))
    await store.initialize()
    config = VideoGenerationConfig(
        provider="openai",
        model="sora",
        api_key=SecretStr("sk-video-test"),
    )
    engine = AsyncVideoGenerationTools(config, store)

    raw = await engine.generate_video(
        "a sunset over the ocean",
        user_id="user-1",
        agent_id="agent-1",
        chat_id="chat-1",
        reference_images=["https://example.com/ref.png"],
    )
    body = json.loads(raw)
    assert body["status"] == "pending"
    assert body["task_type"] == "video_generate"
    assert body["mode"] == "I2V (image-to-video)"

    task_id = str(body["task_id"])
    task = await store.get_task(task_id)
    assert task is not None
    assert task.status == TaskStatus.PENDING
    assert task.task_type == "video_generate"
    assert task.payload["prompt"] == "a sunset over the ocean"
    assert task.payload["api_key"] == "sk-video-test"
    assert task.payload["agent_id"] == "agent-1"
    assert task.payload["chat_id"] == "chat-1"


@pytest.mark.asyncio
async def test_async_video_engine_applies_payload_postprocessor(tmp_path: Path) -> None:
    store = SQLiteTaskStore(db_path=str(tmp_path / "video-tasks-post.db"))
    await store.initialize()
    config = VideoGenerationConfig(
        provider="openai",
        model="sora",
        api_key=SecretStr("sk-video-test"),
    )

    def _postprocess(payload: dict[str, object]) -> dict[str, object]:
        sealed = dict(payload)
        sealed.pop("api_key", None)
        sealed["api_key_enc"] = "ciphertext"
        return sealed

    engine = AsyncVideoGenerationTools(
        config,
        store,
        payload_postprocessor=_postprocess,
    )

    raw = await engine.generate_video("a mountain scene")
    task_id = json.loads(raw)["task_id"]
    task = await store.get_task(str(task_id))
    assert task is not None
    assert "api_key" not in task.payload
    assert task.payload["api_key_enc"] == "ciphertext"


# ---------------------------------------------------------------------------
# VideoGenerationTools: URL extraction → extra_params chain tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVideoEngineUrlExtraction:
    """Verify video_engine extracts URLs from reference_videos and injects into extra_params."""

    async def test_url_extracted_and_passed_to_provider(self) -> None:
        """reference_videos with URLs should populate extra_params['_video_source_urls']."""
        from myrm_agent_harness.toolkits.llms.video.generator import VideoGenerator
        from myrm_agent_harness.toolkits.llms.video.video_engine import VideoGenerationTools

        config = VideoGenerationConfig(
            provider="xai",
            model="grok-imagine-video",
            api_key=SecretStr("test-key"),
        )
        engine = VideoGenerationTools(config)

        captured_extra: dict[str, object] = {}

        async def _mock_generate(self_gen, prompt: str, *, provider_id=None, model=None, **kwargs) -> VideoResult:
            captured_extra.update(kwargs.get("extra_params") or {})
            return VideoResult(provider="xai", model="grok-imagine-video", videos=[], persisted_urls=[])

        with (
            patch.object(VideoGenerator, "generate", _mock_generate),
            patch(
                "myrm_agent_harness.toolkits.llms.video.video_engine._resolve_video_inputs",
                new_callable=AsyncMock,
                return_value=[b"dummy-bytes"],
            ),
        ):
            result_str = await engine.execute(
                "generate",
                prompt="extend the sunset",
                reference_videos=["https://cdn.example.com/video.mp4"],
                duration_seconds=8,
            )
            body = json.loads(result_str)
            assert body.get("task_id") is not None

            # Wait for the background task to complete within the patch context
            await asyncio.sleep(0.1)

        assert "_video_source_urls" in captured_extra
        assert captured_extra["_video_source_urls"] == ["https://cdn.example.com/video.mp4"]

    async def test_local_path_not_in_video_source_urls(self) -> None:
        """Local file paths should NOT appear in _video_source_urls."""
        from myrm_agent_harness.toolkits.llms.video.generator import VideoGenerator
        from myrm_agent_harness.toolkits.llms.video.video_engine import VideoGenerationTools

        config = VideoGenerationConfig(
            provider="xai",
            model="grok-imagine-video",
            api_key=SecretStr("test-key"),
        )
        engine = VideoGenerationTools(config)

        captured_extra: dict[str, object] = {}

        async def _mock_generate(self_gen, prompt: str, *, provider_id=None, model=None, **kwargs) -> VideoResult:
            captured_extra.update(kwargs.get("extra_params") or {})
            return VideoResult(provider="xai", model="grok-imagine-video", videos=[], persisted_urls=[])

        with (
            patch.object(VideoGenerator, "generate", _mock_generate),
            patch(
                "myrm_agent_harness.toolkits.llms.video.video_engine._resolve_video_inputs",
                new_callable=AsyncMock,
                return_value=[b"local-bytes"],
            ),
        ):
            result_str = await engine.execute(
                "generate",
                prompt="edit from local file",
                reference_videos=["/tmp/local_video.mp4"],
            )
            body = json.loads(result_str)
            assert body.get("task_id") is not None

            await asyncio.sleep(0.1)

        assert "_video_source_urls" not in captured_extra

    async def test_mixed_urls_and_local_paths(self) -> None:
        """Only HTTP(S) URLs should be extracted, local paths filtered out."""
        from myrm_agent_harness.toolkits.llms.video.generator import VideoGenerator
        from myrm_agent_harness.toolkits.llms.video.video_engine import VideoGenerationTools

        config = VideoGenerationConfig(
            provider="xai",
            model="grok-imagine-video",
            api_key=SecretStr("test-key"),
        )
        engine = VideoGenerationTools(config)

        captured_extra: dict[str, object] = {}

        async def _mock_generate(self_gen, prompt: str, *, provider_id=None, model=None, **kwargs) -> VideoResult:
            captured_extra.update(kwargs.get("extra_params") or {})
            return VideoResult(provider="xai", model="grok-imagine-video", videos=[], persisted_urls=[])

        with (
            patch.object(VideoGenerator, "generate", _mock_generate),
            patch(
                "myrm_agent_harness.toolkits.llms.video.video_engine._resolve_video_inputs",
                new_callable=AsyncMock,
                return_value=[b"bytes1", b"bytes2"],
            ),
        ):
            result_str = await engine.execute(
                "generate",
                prompt="mixed sources extend",
                reference_videos=[
                    "https://cdn.example.com/video1.mp4",
                    "/tmp/local.mp4",
                    "http://another.cdn.com/v2.mp4",
                ],
                duration_seconds=5,
            )
            body = json.loads(result_str)
            assert body.get("task_id") is not None

            await asyncio.sleep(0.1)

        urls = captured_extra.get("_video_source_urls", [])
        assert urls == [
            "https://cdn.example.com/video1.mp4",
            "http://another.cdn.com/v2.mp4",
        ]

    async def test_v2v_mode_reported_in_response(self) -> None:
        """When reference_videos provided, response should indicate V2V mode."""
        from myrm_agent_harness.toolkits.llms.video.generator import VideoGenerator
        from myrm_agent_harness.toolkits.llms.video.video_engine import VideoGenerationTools

        config = VideoGenerationConfig(
            provider="xai",
            model="grok-imagine-video",
            api_key=SecretStr("test-key"),
        )
        engine = VideoGenerationTools(config)

        async def _mock_generate(self_gen, prompt: str, *, provider_id=None, model=None, **kwargs) -> VideoResult:
            return VideoResult(provider="xai", model="grok-imagine-video", videos=[], persisted_urls=[])

        with (
            patch.object(VideoGenerator, "generate", _mock_generate),
            patch(
                "myrm_agent_harness.toolkits.llms.video.video_engine._resolve_video_inputs",
                new_callable=AsyncMock,
                return_value=[b"dummy"],
            ),
        ):
            result_str = await engine.execute(
                "generate",
                prompt="extend this",
                reference_videos=["https://cdn/v.mp4"],
                duration_seconds=5,
            )

        body = json.loads(result_str)
        assert body["mode"] == "V2V (video-to-video)"


@pytest.mark.asyncio
async def test_generator_moderation_blocked_error_aborts_without_retry() -> None:
    """Verify that ModerationBlockedError skips retries and aborts failover immediately."""
    from unittest.mock import MagicMock
    from myrm_agent_harness.toolkits.llms.video.generator import VideoGenerator
    from myrm_agent_harness.toolkits.llms.video.models import (
        ModerationBlockedError,
        VideoGenerationConfig,
    )
    from myrm_agent_harness.toolkits.llms.video.providers.base import VideoGenerationProvider

    class MockFailingProvider(VideoGenerationProvider):
        @property
        def provider_id(self) -> str:
            return "mock-mod"

        @property
        def display_name(self) -> str:
            return "Mock Mod"

        @property
        def default_model(self) -> str:
            return "mod-1"

        @property
        def supported_models(self):
            return ()

        @property
        def capabilities(self):
            from myrm_agent_harness.toolkits.llms.video.models import ProviderCapabilities
            return ProviderCapabilities()

        async def generate(self, *args, **kwargs):
            raise ModerationBlockedError("Explicit moderation block: NSFW")

    registry = MagicMock()
    registry.get.return_value = MockFailingProvider()
    config = VideoGenerationConfig(provider="mock-mod", model="mod-1", max_retries=3)

    gen = VideoGenerator(config, registry)

    with pytest.raises(ModerationBlockedError) as exc_info:
        await gen.generate("unsafe scene")

    assert "Explicit moderation block: NSFW" in str(exc_info.value)

