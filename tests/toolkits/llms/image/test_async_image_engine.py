"""Tests for AsyncImageGenerationTools enqueue path and payload_postprocessor hook."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.llms.image.async_image_engine import AsyncImageGenerationTools
from myrm_agent_harness.toolkits.llms.image.models import ImageGenerationConfig
from myrm_agent_harness.toolkits.tasks import SQLiteTaskStore


@pytest.fixture
async def temp_store() -> SQLiteTaskStore:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = handle.name

    store = SQLiteTaskStore(db_path=db_path)
    await store.initialize()
    yield store
    Path(db_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_generate_image_returns_task_id_json(temp_store: SQLiteTaskStore) -> None:
    config = ImageGenerationConfig(model="dall-e-3")
    engine = AsyncImageGenerationTools(config, temp_store)

    raw = await engine.generate_image("a blue circle", user_id="user-1")

    payload = json.loads(raw)
    assert payload["status"] == "pending"
    assert isinstance(payload["task_id"], str)
    assert payload["task_id"].startswith("img-")


@pytest.mark.asyncio
async def test_generate_image_persists_execution_snapshot_without_postprocessor(
    temp_store: SQLiteTaskStore,
) -> None:
    config = ImageGenerationConfig(model="flux-pro", api_key="sk-plain")
    engine = AsyncImageGenerationTools(config, temp_store)

    raw = await engine.generate_image(
        "a red cube",
        size="1024x1024",
        user_id="user-2",
        agent_id="agent-2",
        chat_id="chat-2",
    )
    task_id = json.loads(raw)["task_id"]

    task = await temp_store.get_task(task_id)
    assert task is not None
    assert task.payload["model"] == "flux-pro"
    assert task.payload["api_key"] == "sk-plain"
    assert task.payload["chat_id"] == "chat-2"
    assert task.payload["agent_id"] == "agent-2"


@pytest.mark.asyncio
async def test_generate_image_applies_payload_postprocessor_before_persist(
    temp_store: SQLiteTaskStore,
) -> None:
    config = ImageGenerationConfig(model="flux-pro", api_key="sk-seal-me")

    def _seal(payload: dict[str, object]) -> dict[str, object]:
        sealed = dict(payload)
        if "api_key" in sealed:
            sealed["api_key_enc"] = f"enc:{sealed['api_key']}"
            del sealed["api_key"]
        return sealed

    engine = AsyncImageGenerationTools(
        config,
        temp_store,
        payload_postprocessor=_seal,
    )
    raw = await engine.generate_image("a green triangle", user_id="user-3")
    task_id = json.loads(raw)["task_id"]

    task = await temp_store.get_task(task_id)
    assert task is not None
    assert "api_key" not in task.payload
    assert task.payload["api_key_enc"] == "enc:sk-seal-me"


@pytest.mark.asyncio
async def test_generate_image_persists_allow_private_networks_flag(temp_store: SQLiteTaskStore) -> None:
    config = ImageGenerationConfig(model="dall-e-3")
    engine = AsyncImageGenerationTools(config, temp_store, allow_private_networks=False)

    raw = await engine.generate_image(
        "style transfer",
        reference_image_urls=["https://example.com/ref.png"],
    )
    task_id = json.loads(raw)["task_id"]

    task = await temp_store.get_task(task_id)
    assert task is not None
    assert task.payload["allow_private_networks"] is False
