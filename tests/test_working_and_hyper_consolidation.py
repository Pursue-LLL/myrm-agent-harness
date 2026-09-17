"""Unit tests for LocalWorkingMemoryBlock and HyperConsolidationMemoryBlock."""

import asyncio

import pytest

from myrm_agent_harness.agent.context_management.working_memory import (
    LocalWorkingMemoryBlock,
    SubtaskStatus,
)
from myrm_agent_harness.toolkits.memory.consolidation import HyperConsolidator
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


def test_local_working_memory_block_lifecycle() -> None:
    """Test LocalWorkingMemoryBlock creation, update, and markdown formatting."""
    LocalWorkingMemoryBlock.reset()

    # 1. Initialize
    state = LocalWorkingMemoryBlock.initialize(
        goal="Migrate database to SQLite with WAL mode",
        initial_subtasks=["Inspect schema", "Apply migration script"],
    )
    assert state.goal == "Migrate database to SQLite with WAL mode"
    assert len(state.subtasks) == 2
    assert state.subtasks[0].id == "step-1"
    assert state.subtasks[0].status == SubtaskStatus.PENDING

    # 2. Add subtask & update status
    new_sub = LocalWorkingMemoryBlock.add_subtask("Verify database integrity")
    assert new_sub is not None
    assert new_sub.id == "step-3"

    ok = LocalWorkingMemoryBlock.update_subtask("step-1", SubtaskStatus.COMPLETED, notes="schema clean")
    assert ok is True
    ok_in_prog = LocalWorkingMemoryBlock.update_subtask("step-2", SubtaskStatus.IN_PROGRESS)
    assert ok_in_prog is True

    # 3. Scratchpad & traps
    LocalWorkingMemoryBlock.set_scratchpad("db_path", "/var/data/app.db")
    assert LocalWorkingMemoryBlock.get_scratchpad("db_path") == "/var/data/app.db"

    LocalWorkingMemoryBlock.record_trap(
        fingerprint="database_is_locked",
        avoidance_rule="Enable busy_timeout=5000ms before transactions",
        tool_name="sqlite_exec",
    )

    # 4. Turn tail markdown check
    markdown = LocalWorkingMemoryBlock.format_turn_tail_markdown()
    assert "<working_board>" in markdown
    assert "**Goal**: Migrate database to SQLite with WAL mode" in markdown
    assert "[x] step-1: Inspect schema (schema clean)" in markdown
    assert "[>] step-2: Apply migration script" in markdown
    assert "[ ] step-3: Verify database integrity" in markdown
    assert "busy_timeout=5000ms" in markdown
    assert "</working_board>" in markdown

    # 5. Serialization & restoration
    data = LocalWorkingMemoryBlock.to_dict()
    LocalWorkingMemoryBlock.reset()
    assert LocalWorkingMemoryBlock.get_state() is None

    restored = LocalWorkingMemoryBlock.from_dict(data)
    assert restored.goal == "Migrate database to SQLite with WAL mode"
    assert len(restored.subtasks) == 3
    assert len(restored.traps) == 1
    assert restored.scratchpad["db_path"] == "/var/data/app.db"

    LocalWorkingMemoryBlock.reset()


def test_local_working_memory_prewarm_prior_traps() -> None:
    """Validate prewarming prior historical procedural rules into working memory."""
    LocalWorkingMemoryBlock.reset()

    prior_traps = [
        {
            "fingerprint": "rate_limit_429",
            "avoidance_rule": "Attach custom User-Agent and back off with jitter",
            "tool_name": "http_fetch",
        }
    ]

    state = LocalWorkingMemoryBlock.initialize(
        goal="Batch crawl SEC filings",
        initial_subtasks=["Fetch index"],
        prior_traps=prior_traps,
    )

    assert len(state.traps) == 1
    assert state.traps[0].fingerprint == "rate_limit_429"
    assert state.traps[0].occurred_turn == 0

    markdown = LocalWorkingMemoryBlock.format_turn_tail_markdown()
    assert "[Prior]" in markdown
    assert "Attach custom User-Agent and back off with jitter" in markdown

    LocalWorkingMemoryBlock.reset()


@pytest.mark.asyncio
async def test_local_working_memory_block_contextvar_isolation() -> None:
    """Verify ContextVar isolation between concurrent coroutines."""
    LocalWorkingMemoryBlock.reset()

    async def worker_a() -> str:
        LocalWorkingMemoryBlock.initialize(goal="Task Alpha")
        await asyncio.sleep(0.01)
        state = LocalWorkingMemoryBlock.get_state()
        return state.goal if state else ""

    async def worker_b() -> str:
        LocalWorkingMemoryBlock.initialize(goal="Task Beta")
        await asyncio.sleep(0.01)
        state = LocalWorkingMemoryBlock.get_state()
        return state.goal if state else ""

    res_a, res_b = await asyncio.gather(worker_a(), worker_b())
    assert res_a == "Task Alpha"
    assert res_b == "Task Beta"
    LocalWorkingMemoryBlock.reset()


@pytest.mark.asyncio
async def test_hyper_consolidator_gatekeeper_bypass() -> None:
    """Verify trivial conversations (turns <= 1, no subtasks) bypass consolidation."""
    LocalWorkingMemoryBlock.reset()
    LocalWorkingMemoryBlock.initialize(goal="Trivial question")

    consolidator = HyperConsolidator()
    digest, rules = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "What time is it?"}],
        chat_id="chat-trivial",
    )

    assert digest is None
    assert len(rules) == 0
    # Workbench must be reset after run
    assert LocalWorkingMemoryBlock.get_state() is None


@pytest.mark.asyncio
async def test_hyper_consolidator_distillation_and_procedural_rules() -> None:
    """Verify rich long-horizon session distills TaskDigest and self-healing ProceduralMemory."""
    LocalWorkingMemoryBlock.reset()
    LocalWorkingMemoryBlock.initialize(
        goal="Audit security headers and configure Content-Security-Policy",
        initial_subtasks=["Scan endpoint headers", "Generate CSP directive", "Test deployment"],
    )
    LocalWorkingMemoryBlock.update_subtask("step-1", SubtaskStatus.COMPLETED)
    LocalWorkingMemoryBlock.update_subtask("step-2", SubtaskStatus.COMPLETED)
    LocalWorkingMemoryBlock.update_subtask("step-3", SubtaskStatus.COMPLETED)
    LocalWorkingMemoryBlock.advance_turn()
    LocalWorkingMemoryBlock.advance_turn()
    LocalWorkingMemoryBlock.set_scratchpad("csp_sha", "sha256-abcdef123456")

    LocalWorkingMemoryBlock.record_trap(
        fingerprint="inline_script_blocked",
        avoidance_rule="Use nonces rather than unsafe-inline in script-src",
        tool_name="browser_eval",
    )
    LocalWorkingMemoryBlock.resolve_trap("inline_script_blocked")
    LocalWorkingMemoryBlock.set_status("completed")

    consolidator = HyperConsolidator()
    digest, rules = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "Audit security headers"}],
        chat_id="chat-security-42",
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

    # In-memory working block must be cleaned up
    assert LocalWorkingMemoryBlock.get_state() is None


def test_local_working_memory_resolve_trap() -> None:
    """Verify that a recorded trap can be marked as resolved and rendered with ✅ [Resolved]."""
    LocalWorkingMemoryBlock.reset()
    LocalWorkingMemoryBlock.initialize(goal="Self-healing test")
    LocalWorkingMemoryBlock.record_trap(
        fingerprint="rate_limit_429",
        avoidance_rule="Apply exponential backoff with jitter",
        tool_name="web_fetch",
    )

    state = LocalWorkingMemoryBlock.get_state()
    assert state is not None
    assert len(state.traps) == 1
    assert state.traps[0].resolved is False

    # Mark as resolved
    success = LocalWorkingMemoryBlock.resolve_trap("rate_limit_429")
    assert success is True
    assert state.traps[0].resolved is True

    # Check Markdown rendering
    md = LocalWorkingMemoryBlock.format_turn_tail_markdown()
    assert "✅ [Resolved] [web_fetch] Apply exponential backoff with jitter" in md

    # Check serialization roundtrip
    serialized = LocalWorkingMemoryBlock.to_dict()
    assert serialized["traps"][0]["resolved"] is True

    restored = LocalWorkingMemoryBlock.from_dict(serialized)
    assert restored.traps[0].resolved is True
    LocalWorkingMemoryBlock.reset()


@pytest.mark.asyncio
async def test_hyper_consolidator_persistence_with_memory_manager() -> None:
    """Verify HyperConsolidator correctly invokes relational.create_rule and manager.store."""
    LocalWorkingMemoryBlock.reset()
    LocalWorkingMemoryBlock.initialize(
        goal="Configure production Redis Sentinel",
        initial_subtasks=["Check quorum", "Apply failover timeout"],
    )
    LocalWorkingMemoryBlock.advance_turn()
    LocalWorkingMemoryBlock.advance_turn()
    LocalWorkingMemoryBlock.record_trap(
        fingerprint="sentinel_down_after_split",
        avoidance_rule="Set down-after-milliseconds to at least 5000ms",
        tool_name="redis_cli",
    )
    LocalWorkingMemoryBlock.resolve_trap("sentinel_down_after_split")
    LocalWorkingMemoryBlock.set_status("completed")

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
    digest, rules = await consolidator.consolidate_session(
        messages=[{"role": "user", "content": "Purity test"}],
        chat_id="chat-purity-101",
    )

    assert digest is not None
    # Exactly ONE rule must be consolidated: the verified one
    assert len(rules) == 1
    assert rules[0].error_fingerprint == "network_timeout_1001"
    assert rules[0].action == "Retry with 10s backoff"
    assert rules[0].resolution_steps == ["Retry with 10s backoff"]

    # Verify working block is clean
    assert LocalWorkingMemoryBlock.get_state() is None
