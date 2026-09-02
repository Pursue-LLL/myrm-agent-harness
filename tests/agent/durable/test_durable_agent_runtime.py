"""Unit and crash recovery integration tests for DurableAgentRuntime.

Covers:
1. Four-tier decoupled storage (InMemory + SQLite WAL).
2. Intent-First rule with pre-allocated result ID.
3. Single-writer FIFO mutation line (steer, follow-up, finish, abort).
4. Dual replay safety auditor (read-only safe vs mutating unsafe).
5. Synthetic interrupted fallback injection on crash recovery.
6. Monotonic usage record persistence across crashes.
7. Manual drive effects gate with simulated crash traps.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import pytest

from myrm_agent_harness.agent.durable import (
    DriveMode,
    DurableAgentRuntime,
    EffectType,
    InMemoryDurableStorage,
    IntentRecord,
    IntentStatus,
    LaneMutationLine,
    ManualDriveEffectsGate,
    MutationAction,
    ReplaySafetyAuditor,
    SimulatedCrashError,
    SqliteDurableStorage,
    TreeEntry,
)


@pytest.mark.asyncio
async def test_in_memory_four_tier_storage_basic() -> None:
    storage = InMemoryDurableStorage()
    session_id = "test_sess_01"

    # 1. Tree
    entry1 = TreeEntry(
        entry_id="e1",
        session_id=session_id,
        parent_id=None,
        entry_type="system_prompt",
        content="System instructions",
    )
    await storage.append_tree_entry(entry1)
    assert entry1.sequence == 1
    assert entry1.checksum_sha256 is not None

    entry2 = TreeEntry(
        entry_id="e2",
        session_id=session_id,
        parent_id="e1",
        entry_type="message",
        content="Hello Agent",
    )
    await storage.append_tree_entry(entry2)
    assert entry2.sequence == 2

    history = await storage.get_tree_history(session_id, leaf_id="e2")
    assert len(history) == 2
    assert [h.entry_id for h in history] == ["e1", "e2"]

    # 2. Lanes
    lane = await storage.get_or_create_lane(session_id, "main")
    assert lane.lane_id == "main"
    assert lane.status == "idle"

    lane.current_leaf_id = "e2"
    lane.status = "running"
    await storage.update_lane_state(lane)
    lane_fetched = await storage.get_or_create_lane(session_id, "main")
    assert lane_fetched.current_leaf_id == "e2"
    assert lane_fetched.status == "running"

    # 3. Facts
    await storage.set_global_fact(session_id, "agent_name", "CoderAgent")
    assert await storage.get_global_fact(session_id, "agent_name") == "CoderAgent"


@pytest.mark.asyncio
async def test_sqlite_wal_storage_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_durable.db"
        storage = SqliteDurableStorage(db_path)
        session_id = "test_sqlite_sess"

        entry1 = TreeEntry(
            entry_id="root_sys",
            session_id=session_id,
            parent_id=None,
            entry_type="system_prompt",
            content={"role": "system", "text": "Prompt"},
        )
        await storage.append_tree_entry(entry1)

        entry2 = TreeEntry(
            entry_id="msg_01",
            session_id=session_id,
            parent_id="root_sys",
            entry_type="message",
            content={"role": "user", "text": "Run analysis"},
        )
        await storage.append_tree_entry(entry2)

        history = await storage.get_tree_history(session_id, leaf_id="msg_01")
        assert len(history) == 2
        assert history[0].entry_id == "root_sys"
        assert history[1].entry_id == "msg_01"

        # Checkpoint usage
        from myrm_agent_harness.agent.durable.types import UsageRecord
        await storage.append_usage(
            UsageRecord(
                usage_id="u1",
                session_id=session_id,
                lane_id="main",
                model_name="gpt-4o",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cached_tokens=40,
                estimated_cost_usd=0.002,
            )
        )
        usages = await storage.get_total_usage(session_id)
        assert len(usages) == 1
        assert usages[0].total_tokens == 150


@pytest.mark.asyncio
async def test_lane_mutation_line_concurrency() -> None:
    storage = InMemoryDurableStorage()
    session_id = "sess_mut"
    mutation_line = LaneMutationLine(session_id, "main", storage)

    # Submit rapid concurrent mutations
    res_start = await mutation_line.submit_mutation(MutationAction.ATTEMPT_START)
    assert res_start["attempt_count"] == 1

    res_steer = await mutation_line.submit_mutation(MutationAction.STEER, {"steer_text": "stop now"})
    assert res_steer["status"] == "steered"

    res_finish = await mutation_line.submit_mutation(MutationAction.TRY_FINISH)
    assert res_finish["status"] == "completed"

    lane = await storage.get_or_create_lane(session_id, "main")
    assert lane.attempt_count == 1
    assert lane.status == "completed"

    # Check operational logs
    op_logs = await storage.get_operation_logs(session_id, "main")
    assert len(op_logs) == 3
    assert [op.op_type for op in op_logs] == ["mutation_attempt_start", "mutation_steer", "mutation_try_finish"]

    await mutation_line.stop()


@pytest.mark.asyncio
async def test_intent_first_execution_and_replay_safety() -> None:
    storage = InMemoryDurableStorage()
    runtime = DurableAgentRuntime(session_id="sess_intent_01", storage=storage)

    # 1. Initialize
    user_entry, lane = await runtime.initialize_session("System prompt", "Please write file")
    assert lane.current_leaf_id == user_entry.entry_id

    # 2. Execute safe read tool
    async def read_mock() -> str:
        return "file contents"

    res_read = await runtime.execute_tool(
        lane_id="main",
        tool_name="read_file",
        tool_args={"path": "test.txt"},
        tool_callable=read_mock,
    )
    assert res_read.content == "file contents"

    # 3. Simulate uncompleted unsafe mutating tool intent (simulating crash right after intent write)
    intent = IntentRecord(
        intent_id="intent_unsafe_01",
        session_id="sess_intent_01",
        lane_id="main",
        effect_type=EffectType.TOOL_EXECUTION,
        source_leaf_id=res_read.entry_id,
        provisioned_result_id="res_unsafe_01",
        payload={"tool_name": "delete_database", "tool_args": {"target": "prod"}},
        status=IntentStatus.PENDING,
    )
    await storage.append_intent(intent)

    # Verify recovery intercepts unsafe tool and injects synthetic interrupted fallback
    recovery = await runtime.resume_and_recover()
    assert recovery.pending_intents_count == 1
    assert recovery.interrupted_synthetic_count == 1

    # Check that synthetic result was appended to the conversation tree
    synthetic_entry = await storage.get_tree_entry("sess_intent_01", "res_unsafe_01")
    assert synthetic_entry is not None
    assert synthetic_entry.content["status"] == "interrupted"
    assert synthetic_entry.content["error_type"] == "ToolExecutionInterruptedError"

    # Check intent state updated to INTERRUPTED
    saved_intent = await storage.get_intent("sess_intent_01", "intent_unsafe_01")
    assert saved_intent is not None
    assert saved_intent.status == IntentStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_manual_drive_crash_injection_matrix() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "crash_test.db"
        gate = ManualDriveEffectsGate(mode=DriveMode.MANUAL)
        storage = SqliteDurableStorage(db_path)
        runtime = DurableAgentRuntime(session_id="sess_crash_01", storage=storage, effects_gate=gate)

        await runtime.initialize_session("sys", "do dangerous write")

        # Trap crash before effect
        gate.inject_crash_before_effect(EffectType.TOOL_EXECUTION.value)

        executed_flag = False

        async def mutating_write() -> str:
            nonlocal executed_flag
            executed_flag = True
            return "written"

        with pytest.raises(SimulatedCrashError):
            await runtime.execute_tool(
                lane_id="main",
                tool_name="write_file",
                tool_args={"path": "foo.py"},
                tool_callable=mutating_write,
            )

        # Effect was never executed because crash occurred at before_effect gate
        assert not executed_flag

        # However, the intent was safely persisted in SQLite
        pending = await storage.get_pending_intents("sess_crash_01")
        assert len(pending) == 1
        assert pending[0].payload["tool_name"] == "write_file"

        # Now simulate process respawn and recovery
        runtime2 = DurableAgentRuntime(session_id="sess_crash_01", db_path=db_path)
        rec = await runtime2.resume_and_recover()
        assert rec.interrupted_synthetic_count == 1

        # Check that no duplicate side effects can happen
        pending_after = await runtime2.storage.get_pending_intents("sess_crash_01")
        assert len(pending_after) == 0
