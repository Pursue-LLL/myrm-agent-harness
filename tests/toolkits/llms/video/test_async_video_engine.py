"""Tests for async video enqueue adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from myrm_agent_harness.toolkits.llms.video.async_video_engine import AsyncVideoGenerationTools
from myrm_agent_harness.toolkits.llms.video.models import VideoGenerationConfig
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
