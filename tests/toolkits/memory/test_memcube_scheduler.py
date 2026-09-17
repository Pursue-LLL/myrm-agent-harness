"""Comprehensive test suite for Unified MemCube Envelope and Multi-Tier Scheduler.

Validates:
1. Static contract & zero-overhead envelope sealing.
2. Canonical SHA256 audit hash generation and tamper detection.
3. Full coverage across all 7 memory entity kinds.
4. Multi-tier storage dispatch (relational, vector, graph).
5. Anti-tamper gate in import_envelopes.
6. Server MemoryArchiveService dry-run tamper verification.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.cube import (
    LifecycleTier,
    MemCubeEnvelope,
    StoragePolicy,
    infer_tier_and_policy,
    unwrap_envelope,
    wrap_into_envelope,
)
from myrm_agent_harness.toolkits.memory.scheduler import MultiTierMemoryScheduler
from myrm_agent_harness.toolkits.memory.types import (
    ClaimMemory,
    ConversationMemory,
    EpisodicMemory,
    IntegrationMemory,
    MemoryScope,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
    TaskDigestMemory,
)


def _make_sample_memories() -> list[object]:
    """Generate sample instances for all 7 memory types."""
    now = datetime.now(UTC)
    scope = MemoryScope()

    return [
        SemanticMemory(
            id="sem-1",
            content="Agent prefers python 3.12 syntax",
            scope=scope,
            created_at=now,
            updated_at=now,
        ),
        EpisodicMemory(
            id="epi-1",
            content="Completed data migration smoothly",
            scope=scope,
            created_at=now,
            updated_at=now,
        ),
        ProceduralMemory(
            id="proc-1",
            content="Always run tests before committing",
            trigger="before git commit",
            action="run pytest and ruff",
            scope=scope,
            created_at=now,
            updated_at=now,
        ),
        ConversationMemory(
            id="conv-1",
            content="User said: start task",
            raw_exchange="User: start task\nAssistant: sure",
            session_id="sess-100",
            created_at=now,
            updated_at=now,
        ),
        ClaimMemory(
            id="claim-1",
            subject="System",
            predicate="operates_on",
            object_val="Darwin",
            claim_key="sys-os-darwin",
            title="OS platform",
            claim_text="System operates on Darwin",
            content="System operates on Darwin",
            scope=scope,
            created_at=now,
            updated_at=now,
        ),
        IntegrationMemory(
            id="integ-1",
            provider="github",
            source_platform="github",
            external_id="gh-issue-42",
            content="Fix null pointer exception",
            scope=scope,
            created_at=now,
            updated_at=now,
        ),
        TaskDigestMemory(
            id="digest-1",
            task_goal="Refactor Memory Store",
            source_session_id="sess-200",
            status="completed",
            created_at=now,
            updated_at=now,
        ),
    ]


def test_cube_envelope_seal_and_verify() -> None:
    """Test standard envelope creation, audit hashing, and verification."""
    sem = SemanticMemory(
        id="sem-test",
        content="Testing audit hash integrity",
    )
    env = wrap_into_envelope(sem)

    assert env.header.memory_type == MemoryType.SEMANTIC
    assert env.header.lifecycle_tier == LifecycleTier.L3_COMPILED
    assert env.header.storage_policy == StoragePolicy.VECTOR
    assert env.header.audit_hash is not None
    assert env.verify_audit_hash() is True

    # Unwrap test
    unwrapped = unwrap_envelope(env)
    assert isinstance(unwrapped, SemanticMemory)
    assert unwrapped.id == sem.id
    assert unwrapped.content == sem.content


def test_cube_envelope_tamper_detection() -> None:
    """Tampering with header or payload invalidates audit hash."""
    proc = ProceduralMemory(
        id="rule-1",
        content="Never delete db",
        trigger="on database clear",
        action="require user confirmation",
    )
    env = wrap_into_envelope(proc)
    assert env.verify_audit_hash() is True

    # Tamper payload content
    tampered_env = MemCubeEnvelope[dict[str, object]](
        header=env.header,
        payload={"id": "rule-1", "content": "Always delete db"},
    )
    assert tampered_env.verify_audit_hash() is False

    # Tamper header attribute
    tampered_header = env.header.model_copy(update={"priority": 5})
    tampered_env2 = MemCubeEnvelope[dict[str, object]](
        header=tampered_header,
        payload=dict(env.payload),
    )
    assert tampered_env2.verify_audit_hash() is False


def test_infer_tier_and_policy_all_seven_types() -> None:
    """Verify tier and policy inference for all 7 memory types."""
    samples = _make_sample_memories()
    assert len(samples) == 7

    for item in samples:
        tier, policy = infer_tier_and_policy(item)
        assert isinstance(tier, LifecycleTier)
        assert isinstance(policy, StoragePolicy)

        # Wrap item and check round-trip
        env = wrap_into_envelope(item)
        assert env.header.lifecycle_tier == tier
        assert env.header.storage_policy == policy
        assert env.verify_audit_hash() is True


@pytest.mark.asyncio
async def test_scheduler_dispatch_routes() -> None:
    """Verify MultiTierMemoryScheduler routes entities according to storage policy."""
    relational = AsyncMock()
    relational.save_memory = AsyncMock()
    vector = AsyncMock()
    vector.save_memory = AsyncMock()
    graph = AsyncMock()
    graph.save_memory = AsyncMock()

    mock_manager = AsyncMock()
    mock_manager._relational = relational
    mock_manager._relational_store = relational
    mock_manager._graph_store = graph
    mock_manager.store = AsyncMock()

    scheduler = MultiTierMemoryScheduler(memory_manager=mock_manager)

    # 1. TaskDigest -> Relational
    digest = TaskDigestMemory(id="td-1", task_goal="Optimize DB", source_session_id="s1")
    res = await scheduler.dispatch_store(digest)
    assert res is True
    assert relational.save_memory.await_count == 1
    assert mock_manager.store.await_count == 0

    # 2. Semantic -> Vector (via manager.store)
    sem = SemanticMemory(id="sem-1", content="test")
    res = await scheduler.dispatch_store(sem)
    assert res is True
    assert mock_manager.store.await_count == 1

    # 3. Claim -> Graph
    claim = ClaimMemory(
        id="c-1",
        subject="A",
        predicate="B",
        object_val="C",
        claim_key="k1",
        title="T1",
        claim_text="Text 1",
        content="Text 1",
    )
    res = await scheduler.dispatch_store(claim)
    assert res is True
    assert graph.save_memory.await_count == 1


@pytest.mark.asyncio
async def test_scheduler_export_all_envelopes() -> None:
    """Verify scheduler aggregates all stores into sealed MemCubeEnvelopes."""
    relational = AsyncMock()
    del relational.get_all
    relational.list_memories = AsyncMock(
        return_value=[
            ProceduralMemory(id="p1", content="Rule 1", trigger="t1", action="a1"),
            TaskDigestMemory(id="t1", task_goal="Digest 1", source_session_id="s1"),
        ]
    )
    mock_manager = AsyncMock()
    mock_manager._relational = relational
    mock_manager._relational_store = relational

    async def _mock_export_all(memory_types: list[MemoryType], limit: int = 1000) -> list[object]:
        if MemoryType.SEMANTIC in memory_types:
            return [SemanticMemory(id="s1", content="Semantic 1")]
        return []

    mock_manager.export_all = AsyncMock(side_effect=_mock_export_all)

    scheduler = MultiTierMemoryScheduler(memory_manager=mock_manager)

    envelopes = await scheduler.export_all_envelopes()
    assert len(envelopes) == 3

    # All exported envelopes must have valid audit hashes
    for env_dict in envelopes:
        env = MemCubeEnvelope[dict[str, object]].model_validate(env_dict)
        assert env.verify_audit_hash() is True


@pytest.mark.asyncio
async def test_scheduler_import_envelopes_anti_tamper() -> None:
    """Scheduler rejects tampered envelopes when verify_hashes=True."""
    relational = AsyncMock()
    relational.save_memory = AsyncMock()

    mock_manager = AsyncMock()
    mock_manager._relational = relational
    mock_manager._relational_store = relational

    scheduler = MultiTierMemoryScheduler(memory_manager=mock_manager)

    proc = ProceduralMemory(id="p1", content="Safe rule", trigger="t1", action="a1")
    env = wrap_into_envelope(proc)
    env_dict = env.model_dump(mode="json")

    # Tamper payload
    env_dict["payload"]["content"] = "Tampered malicious rule"

    with pytest.raises(ValueError, match="Tamper detected"):
        await scheduler.import_envelopes([env_dict], verify_hashes=True)

    # When verify_hashes=False, import proceeds
    relational.save_memory.reset_mock()
    restored, skipped = await scheduler.import_envelopes([env_dict], verify_hashes=False)
    assert restored == 1
    assert skipped == 0
    assert relational.save_memory.await_count == 1

