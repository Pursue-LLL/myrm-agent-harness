"""Unit tests for HyperConsolidator: session distillation, rule persistence, working-memory purity guard."""

from collections.abc import Generator

import pytest

from myrm_agent_harness.agent.context_management.working_memory import (
    LocalWorkingMemoryBlock,
    SubtaskStatus,
)
from myrm_agent_harness.toolkits.memory.consolidation import (
    ConsolidationSubtask,
    ConsolidationTrap,
    HyperConsolidator,
    WorkingMemorySnapshot,
)
from myrm_agent_harness.toolkits.memory.relational.sqlite_store import (
    SQLiteRelationalStore,
)
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory,
    MemoryType,
    ProceduralMemory,
    RuleSource,
    TaskDigestMemory,
)


@pytest.fixture(autouse=True)
def reset_working_memory() -> Generator[None]:
    """LocalWorkingMemoryBlock is process-global; isolate every test from state leaked by others."""
    LocalWorkingMemoryBlock.reset()
    yield
    LocalWorkingMemoryBlock.reset()


def test_task_digest_memory_schema() -> None:
    """Validate TaskDigestMemory instantiation and AnyMemory type inclusion."""
    digest = TaskDigestMemory(
        id="digest-test-1",
        task_goal="Build benchmark system",
        status="completed",
        completed_steps=["Design", "Implement", "Benchmark"],
        artifact_paths=["/tmp/benchmark.py"],
        artifact_hashes={"/tmp/benchmark.py": "abc123hash"},
        key_findings=["Throughput improved by 35%"],
        error_lessons=["Use uv pip instead of pip in sandbox"],
        tool_call_count=18,
        source_session_id="chat-100",
    )

    assert digest.memory_type == MemoryType.TASK_DIGEST
    assert digest.status == "completed"
    assert len(digest.completed_steps) == 3
    assert isinstance(digest, AnyMemory)


@pytest.mark.asyncio
async def test_hyper_consolidator_gatekeeper_bypass() -> None:
    """Verify trivial conversations (turns <= 1, no subtasks) bypass consolidation."""
    snapshot = WorkingMemorySnapshot(goal="Trivial question", active_turn=1)

    consolidator = HyperConsolidator()
    digest, rules = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "What time is it?"}],
        chat_id="chat-trivial",
        snapshot=snapshot,
    )

    assert digest is None
    assert len(rules) == 0


@pytest.mark.asyncio
async def test_hyper_consolidator_status_normalization() -> None:
    """Verify non-terminal snapshot statuses normalize to completed digests."""
    snapshot = WorkingMemorySnapshot(
        goal="Normalize me",
        active_turn=3,
        status="active",
        subtasks=[ConsolidationSubtask(title="Done thing", completed=True)],
    )
    consolidator = HyperConsolidator()
    digest, _ = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "go"}],
        chat_id="chat-norm",
        snapshot=snapshot,
    )
    assert digest is not None
    assert digest.status == "completed"


@pytest.mark.asyncio
async def test_hyper_consolidator_store_batch_path() -> None:
    """Verify the store_batch fast path is used when the manager offers it."""
    snapshot = WorkingMemorySnapshot(
        goal="Batch persist",
        active_turn=2,
        status="completed",
        subtasks=[ConsolidationSubtask(title="Step", completed=True)],
        traps=[
            ConsolidationTrap(
                fingerprint="fp-batch",
                avoidance_rule="Batch it",
                tool_name="tool_x",
                occurred_turn=1,
                resolved=True,
            )
        ],
    )
    batched: list[object] = []
    stored: list[object] = []

    class BatchManager:
        async def store_batch(self, rules: object) -> None:
            batched.append(rules)

        async def store(self, memory: object) -> None:
            stored.append(memory)

    consolidator = HyperConsolidator(memory_manager=BatchManager())  # type: ignore[arg-type]
    digest, rules = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "go"}],
        chat_id="chat-batch",
        snapshot=snapshot,
    )
    assert digest is not None
    assert len(rules) == 1
    assert len(batched) == 1
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_consolidation_cleanup_task_wires_provider_and_after_run() -> None:
    """Verify the factory threads snapshot provider results and always runs after_run."""
    from myrm_agent_harness.toolkits.memory.consolidation import (
        create_consolidation_cleanup_task,
    )

    seen: list[str] = []
    snapshot = WorkingMemorySnapshot(goal="Factory wired", active_turn=2)

    task = create_consolidation_cleanup_task(
        snapshot_provider=lambda: snapshot,
        after_run=lambda: seen.append("cleaned"),
    )
    await task([{"role": "user", "content": "go"}], "chat-factory")
    assert seen == ["cleaned"]


@pytest.mark.asyncio
async def test_hyper_consolidator_missing_snapshot_bypass() -> None:
    """Verify a missing snapshot bypasses consolidation without touching any global."""
    consolidator = HyperConsolidator()
    digest, rules = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "What time is it?"}],
        chat_id="chat-trivial",
        snapshot=None,
    )

    assert digest is None
    assert len(rules) == 0


@pytest.mark.asyncio
async def test_hyper_consolidator_persists_to_real_sqlite(tmp_path: object) -> None:
    """End-to-end (no mocks): snapshot → digest + rules → real SQLite file → read back."""
    from pathlib import Path

    store = SQLiteRelationalStore(str(Path(str(tmp_path)) / "hyper_e2e.db"))

    class RealDbManager:
        def __init__(self) -> None:
            self._relational = store
            self.episodics: list[object] = []

        async def store(self, memory: object) -> None:
            self.episodics.append(memory)

    snapshot = WorkingMemorySnapshot(
        goal="Ship nightly backup",
        active_turn=3,
        status="completed",
        subtasks=[ConsolidationSubtask(title="Snapshot volume", completed=True)],
        traps=[
            ConsolidationTrap(
                fingerprint="wal_growth",
                avoidance_rule="Checkpoint WAL before backup",
                tool_name="sqlite_cli",
                occurred_turn=2,
                resolved=True,
            )
        ],
    )
    manager = RealDbManager()
    consolidator = HyperConsolidator(memory_manager=manager)  # type: ignore[arg-type]
    digest, rules = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "backup"}],
        chat_id="chat-e2e",
        snapshot=snapshot,
    )
    assert digest is not None
    assert len(rules) == 1

    persisted = await store.get_rule(rules[0].id)
    assert persisted is not None
    assert persisted.error_fingerprint == "wal_growth"
    assert len(manager.episodics) == 1
    await store.close()


@pytest.mark.asyncio
async def test_hyper_consolidator_distillation_and_procedural_rules() -> None:
    """Verify rich long-horizon session distills TaskDigest and self-healing ProceduralMemory."""
    snapshot = WorkingMemorySnapshot(
        goal="Audit security headers and configure Content-Security-Policy",
        active_turn=2,
        status="completed",
        subtasks=[
            ConsolidationSubtask(title="Scan endpoint headers", completed=True),
            ConsolidationSubtask(title="Generate CSP directive", completed=True),
            ConsolidationSubtask(title="Test deployment", completed=True),
        ],
        traps=[
            ConsolidationTrap(
                fingerprint="inline_script_blocked",
                avoidance_rule="Use nonces rather than unsafe-inline in script-src",
                tool_name="browser_eval",
                occurred_turn=1,
                resolved=True,
            )
        ],
        scratchpad={"csp_sha": "sha256-abcdef123456"},
    )

    consolidator = HyperConsolidator()
    digest, rules = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "Audit security headers"}],
        chat_id="chat-security-42",
        snapshot=snapshot,
    )

    assert digest is not None
    assert digest.status == "completed"
    assert digest.task_goal == "Audit security headers and configure Content-Security-Policy"
    assert len(digest.completed_steps) == 3
    assert "csp_sha: sha256-abcdef123456" in digest.key_findings

    assert len(rules) == 1
    proc = rules[0]
    assert proc.error_fingerprint == "inline_script_blocked"
    assert "Use nonces rather than unsafe-inline" in proc.action
    assert proc.resolution_steps == ["Use nonces rather than unsafe-inline in script-src"]


@pytest.mark.asyncio
async def test_hyper_consolidator_persistence_with_memory_manager() -> None:
    """Verify HyperConsolidator correctly invokes relational.create_rule and manager.store."""
    snapshot = WorkingMemorySnapshot(
        goal="Configure production Redis Sentinel",
        active_turn=2,
        status="completed",
        subtasks=[
            ConsolidationSubtask(title="Check quorum", completed=False),
            ConsolidationSubtask(title="Apply failover timeout", completed=False),
        ],
        traps=[
            ConsolidationTrap(
                fingerprint="sentinel_down_after_split",
                avoidance_rule="Set down-after-milliseconds to at least 5000ms",
                tool_name="redis_cli",
                occurred_turn=1,
                resolved=True,
            )
        ],
    )

    stored_rules = []
    stored_episodics = []

    class FakeRelational:
        async def create_rule(self, rule: object) -> None:
            stored_rules.append(rule)

    class FakeMemoryManager:
        def __init__(self) -> None:
            self._relational = FakeRelational()

        async def store(self, memory: object) -> None:
            stored_episodics.append(memory)

    manager = FakeMemoryManager()
    consolidator = HyperConsolidator(memory_manager=manager)  # type: ignore[arg-type]

    digest, rules = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "Setup Redis Sentinel"}],
        chat_id="chat-redis-99",
        snapshot=snapshot,
    )

    assert digest is not None
    assert len(rules) == 1
    assert len(stored_rules) == 1
    assert stored_rules[0].error_fingerprint == "sentinel_down_after_split"
    assert "Set down-after-milliseconds" in stored_rules[0].action

    assert len(stored_episodics) == 1
    assert stored_episodics[0].metadata["event_type"] == "task_digest"
    assert stored_episodics[0].metadata["task_goal"] == "Configure production Redis Sentinel"

    # In-memory working block must be cleaned up
    assert LocalWorkingMemoryBlock.get_state() is None


@pytest.mark.asyncio
async def test_sqlite_procedural_memory_error_fingerprint_roundtrip(tmp_path: object) -> None:
    """Validate ProceduralMemory roundtrip serialization/deserialization retains error_fingerprint."""
    from pathlib import Path

    db_file = str(Path(str(tmp_path)) / "test_proc.db")
    store = SQLiteRelationalStore(db_file)

    rule = ProceduralMemory(
        id="proc-docker-test",
        content="Avoid docker cache corruption: build with --no-cache",
        trigger="error: docker build failed",
        action="docker build --no-cache",
        error_fingerprint="docker_build_cache_corrupt",
        resolution_steps=["clean cache", "rebuild"],
        source=RuleSource.AGENT_SELF,
    )

    # 1. Create rule in SQLite
    saved = await store.create_rule(rule)
    assert saved.id == "proc-docker-test"

    # 2. Retrieve rule from SQLite and verify error_fingerprint & resolution_steps
    retrieved = await store.get_rule("proc-docker-test")
    assert retrieved is not None
    assert retrieved.error_fingerprint == "docker_build_cache_corrupt"
    assert retrieved.resolution_steps == ["clean cache", "rebuild"]

    # 3. Update rule
    retrieved.error_fingerprint = "docker_build_cache_v2"
    retrieved.resolution_steps = ["docker builder prune", "rebuild"]
    await store.update_rule("proc-docker-test", retrieved)

    # 4. Retrieve again to confirm update roundtrip
    updated = await store.get_rule("proc-docker-test")
    assert updated is not None
    assert updated.error_fingerprint == "docker_build_cache_v2"
    assert updated.resolution_steps == ["docker builder prune", "rebuild"]

    await store.close()


@pytest.mark.asyncio
async def test_hyper_consolidator_purity_guard_filters_prior_and_unresolved_traps() -> None:
    """Verify HyperConsolidator skips prior traps (occurred_turn=0) and unresolved traps."""
    LocalWorkingMemoryBlock.reset()
    LocalWorkingMemoryBlock.initialize(
        goal="Purity guard test",
        initial_subtasks=["Step A", "Step B"],
        prior_traps=[
            {
                "fingerprint": "prior_error_403",
                "avoidance_rule": "Send valid User-Agent",
                "tool_name": "web_fetch",
            }
        ],
    )
    LocalWorkingMemoryBlock.update_subtask("step-1", SubtaskStatus.COMPLETED)
    LocalWorkingMemoryBlock.update_subtask("step-2", SubtaskStatus.COMPLETED)
    LocalWorkingMemoryBlock.advance_turn()
    LocalWorkingMemoryBlock.advance_turn()

    # Trap 1: Unresolved trial error (should be ignored)
    LocalWorkingMemoryBlock.record_trap(
        fingerprint="unresolved_experimental_error",
        avoidance_rule="Unproven advice that was never verified",
        tool_name="cmd_run",
    )

    # Trap 2: Verified and resolved trap (should be consolidated)
    LocalWorkingMemoryBlock.record_trap(
        fingerprint="network_timeout_1001",
        avoidance_rule="Retry with 10s backoff",
        tool_name="api_call",
    )
    resolved_ok = LocalWorkingMemoryBlock.resolve_trap("network_timeout_1001")
    assert resolved_ok is True

    LocalWorkingMemoryBlock.set_status("completed")

    consolidator = HyperConsolidator()
    snapshot = LocalWorkingMemoryBlock.to_snapshot()
    digest, rules = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "Purity test"}],
        chat_id="chat-purity-101",
        snapshot=snapshot,  # type: ignore[arg-type]
    )
    LocalWorkingMemoryBlock.reset()

    assert digest is not None
    # Exactly ONE rule must be consolidated: the verified one
    assert len(rules) == 1
    assert rules[0].error_fingerprint == "network_timeout_1001"
    assert rules[0].action == "Retry with 10s backoff"
    assert rules[0].resolution_steps == ["Retry with 10s backoff"]

    # Verify working block is clean
    assert LocalWorkingMemoryBlock.get_state() is None
