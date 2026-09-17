"""Unit tests for LocalWorkingMemoryBlock and HyperConsolidationMemoryBlock."""

import asyncio
from typing import Any

import pytest
from myrm_agent_harness.agent.context_management.working_memory import (
    LocalWorkingMemoryBlock,
    SubtaskStatus,
)
from myrm_agent_harness.toolkits.memory.consolidation import HyperConsolidator
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory,
    MemoryType,
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

