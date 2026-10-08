"""Tests for Ebbinghaus Decay and Tiered Lifecycle Agent runtime integration.

[INPUT]
- toolkits.memory.manager::MemoryManager
- toolkits.memory.decay.lifecycle_manager::TieredStorageLifecycleManager
- toolkits.memory.decay.types::StorageTier

[OUTPUT]
- Pytest test cases verifying Agent runtime consumption of Ebbinghaus decay evaluation and reranking.
"""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.decay import (
    TieredStorageLifecycleManager,
)
from myrm_agent_harness.toolkits.memory.decay.types import (
    StorageTier,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager


def test_agent_runtime_evaluate_memory_lifecycle_decay() -> None:
    """Verify Agent runtime can trigger periodic lifecycle migration via MemoryManager."""
    manager = MemoryManager(
        user_id="test_user",
        config=MemoryConfig(
            embedding_model="text-embedding-3-small", security_scan_enabled=False
        ),
    )
    lifecycle_mgr = TieredStorageLifecycleManager()

    t0 = time.time()
    day_sec = 86400.0

    # Register sample memories with varying age
    lifecycle_mgr.register_memory("mem-fresh", "Active prompt rule", 0.9, created_at=t0)
    lifecycle_mgr.register_memory("mem-warm", "Month old guideline", 0.5, created_at=t0 - 25 * day_sec)
    lifecycle_mgr.register_memory("mem-cold", "Obsolete config", 0.2, created_at=t0 - 80 * day_sec)

    report = manager.evaluate_memory_lifecycle_decay(
        manager=lifecycle_mgr,
        current_time=t0,
    )

    assert report.total_evaluated == 3
    assert report.hot_count >= 1
    assert report.cold_count >= 1
    assert "mem-cold" in report.migrated_memory_ids or any(
        p.memory_id == "mem-cold" for p in lifecycle_mgr.get_profiles_by_tier(StorageTier.COLD)
    )


def test_agent_runtime_rerank_with_temporal_decay() -> None:
    """Verify search candidates are reranked by fusing base similarity and freshness."""
    manager = MemoryManager(
        user_id="test_user",
        config=MemoryConfig(
            embedding_model="text-embedding-3-small", security_scan_enabled=False
        ),
    )
    lifecycle_mgr = TieredStorageLifecycleManager()

    t0 = time.time()
    day_sec = 86400.0

    # Fresh memory with slightly lower similarity, stale memory with slightly higher similarity
    lifecycle_mgr.register_memory("mem-fresh", "Current framework React 19", 0.9, created_at=t0)
    lifecycle_mgr.register_memory("mem-stale", "Deprecated React 16 tip", 0.4, created_at=t0 - 60 * day_sec)
    lifecycle_mgr.evaluate_and_migrate(current_time=t0)

    candidates = [
        ("mem-stale", "Deprecated React 16 tip", 0.88),
        ("mem-fresh", "Current framework React 19", 0.82),
    ]

    # With decay weight = 0.5, fresh memory should overtake stale memory
    reranked = manager.rerank_memories_with_ebbinghaus_decay(
        candidates=candidates,
        lifecycle_manager=lifecycle_mgr,
        decay_weight=0.5,
        exclude_cold=False,
        current_time=t0,
    )

    assert len(reranked) == 2
    assert reranked[0].memory_id == "mem-fresh"
    assert reranked[1].memory_id == "mem-stale"
    assert reranked[0].final_score > reranked[1].final_score


def test_agent_runtime_exclude_cold_candidates() -> None:
    """Verify that cold archived memories are excluded from active retrieval when requested."""
    manager = MemoryManager(
        user_id="test_user",
        config=MemoryConfig(
            embedding_model="text-embedding-3-small", security_scan_enabled=False
        ),
    )
    lifecycle_mgr = TieredStorageLifecycleManager()

    t0 = time.time()
    day_sec = 86400.0

    lifecycle_mgr.register_memory("mem-fresh", "Fresh memory", 0.9, created_at=t0)
    lifecycle_mgr.register_memory("mem-cold", "Cold memory", 0.1, created_at=t0 - 100 * day_sec)
    lifecycle_mgr.evaluate_and_migrate(current_time=t0)

    candidates = [
        ("mem-cold", "Cold memory", 0.95),
        ("mem-fresh", "Fresh memory", 0.70),
    ]

    # Exclude cold
    reranked = manager.rerank_memories_with_ebbinghaus_decay(
        candidates=candidates,
        lifecycle_manager=lifecycle_mgr,
        exclude_cold=True,
        current_time=t0,
    )

    assert len(reranked) == 1
    assert reranked[0].memory_id == "mem-fresh"
