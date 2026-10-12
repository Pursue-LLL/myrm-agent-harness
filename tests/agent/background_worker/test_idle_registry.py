"""IdleTaskRegistry persistence semantics and the aiosqlite-unavailable guards."""

from pathlib import Path

import pytest

from myrm_agent_harness.agent.background_worker import registry as registry_module
from myrm_agent_harness.agent.background_worker.registry import IdleTaskRegistry


@pytest.fixture
def registry(tmp_path: Path) -> IdleTaskRegistry:
    return IdleTaskRegistry(str(tmp_path / "idle.db"))


@pytest.mark.asyncio
async def test_enqueue_deduplicates_a_task_type_that_is_already_pending(registry: IdleTaskRegistry) -> None:
    await registry.enqueue("s1", "cognitive_consolidation", {})
    await registry.enqueue("s1", "cognitive_consolidation", {})

    first = await registry.acquire_next("s1")

    assert first is not None
    assert first.payload == {}
    assert await registry.acquire_next("s1") is None


@pytest.mark.asyncio
async def test_payload_round_trips_as_json_object(registry: IdleTaskRegistry) -> None:
    await registry.enqueue("s1", "context_compaction", {"chat_id": "c1"})

    record = await registry.acquire_next("s1")

    assert record is not None
    assert record.payload == {"chat_id": "c1"}


@pytest.mark.asyncio
async def test_every_operation_is_a_noop_when_aiosqlite_is_unavailable(
    registry: IdleTaskRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "aiosqlite", None)

    await registry.init_db()
    await registry.enqueue("s1", "cognitive_consolidation", {})
    assert await registry.acquire_next("s1") is None
    await registry.requeue(1)
    await registry.mark_completed(1)
    await registry.mark_error(1)
    assert await registry.cleanup_old_tasks() == 0
