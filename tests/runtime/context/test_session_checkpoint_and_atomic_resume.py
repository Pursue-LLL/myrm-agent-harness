"""Unit tests for Session State Checkpoint and Atomic Resume Protocol.

Verifies step-level checkpoint lifecycle, crash interruption detection,
idempotency evaluation for interrupted tool calls, on-disk atomic persistence,
and timeline rewind branching.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.runtime.context.session_checkpoint_storage import (
    SessionCheckpointStorage,
)
from myrm_agent_harness.runtime.context.session_checkpoint_types import (
    CheckpointStepStatus,
    SessionCheckpointConfig,
    ToolActionRecoveryKind,
)
from myrm_agent_harness.runtime.context.session_state_atomic_resume_engine import (
    SessionStateAtomicResumeEngine,
)


def test_standard_step_lifecycle_no_interruption() -> None:
    """Verifies standard step transitions culminating in STEP_COMMITTED without interruptions."""
    engine = SessionStateAtomicResumeEngine()
    session_id = "sess_happy_path"

    # 1. Step start
    engine.start_step(
        session_id=session_id,
        step_index=1,
        messages_count=3,
        workspace_fingerprint="hash_v1",
    )
    assert engine.detect_interruption(session_id) is True

    # 2. Tool invocation begin
    engine.begin_tool_invocation(
        session_id=session_id,
        step_index=1,
        tool_name="read_file",
        call_id="call_001",
        input_args={"file_path": "main.py"},
        workspace_fingerprint="hash_v1",
        messages_count=3,
    )
    assert engine.detect_interruption(session_id) is True

    # 3. Tool invocation complete
    engine.complete_tool_invocation(
        session_id=session_id,
        step_index=1,
        tool_name="read_file",
        call_id="call_001",
        output_preview="print('hello')",
        workspace_fingerprint="hash_v1",
        messages_count=4,
    )

    # 4. Step commit
    engine.commit_step(
        session_id=session_id,
        step_index=1,
        workspace_fingerprint="hash_v1",
        messages_count=5,
    )

    # Completed step has no interruption and cannot resume
    assert engine.detect_interruption(session_id) is False
    decision = engine.evaluate_resume_decision(session_id)
    assert decision.can_resume is False
    assert decision.resume_step_index == 1


def test_read_only_tool_interruption_re_execute_decision() -> None:
    """Verifies that interruption during read-only tool invocation prompts safe re-execution."""
    engine = SessionStateAtomicResumeEngine()
    session_id = "sess_read_crash"

    engine.start_step(
        session_id=session_id,
        step_index=2,
        messages_count=6,
        workspace_fingerprint="hash_read_v1",
    )
    engine.begin_tool_invocation(
        session_id=session_id,
        step_index=2,
        tool_name="web_search",
        call_id="call_search_1",
        input_args={"query": "python 3.13 changelog"},
        workspace_fingerprint="hash_read_v1",
        messages_count=6,
    )

    # Simulated crash: process halted right here in TOOL_INVOKING state
    assert engine.detect_interruption(session_id) is True

    decision = engine.evaluate_resume_decision(session_id)
    assert decision.can_resume is True
    assert decision.resume_step_index == 2
    assert decision.recommended_action == ToolActionRecoveryKind.RE_EXECUTE
    assert decision.divergence_detected is False
    assert "web_search" in decision.prompt_instructions


def test_mutating_tool_idempotency_skip_when_landed() -> None:
    """Verifies mutating tool interruption skips duplicate write if disk fingerprint changed."""
    engine = SessionStateAtomicResumeEngine()
    session_id = "sess_write_crash"

    engine.start_step(
        session_id=session_id,
        step_index=5,
        messages_count=10,
        workspace_fingerprint="initial_hash",
    )
    engine.begin_tool_invocation(
        session_id=session_id,
        step_index=5,
        tool_name="write_to_file",
        call_id="call_write_1",
        input_args={"target_file": "config.yaml"},
        workspace_fingerprint="initial_hash",
        messages_count=10,
    )

    # Scenario A: Disk fingerprint changed (write succeeded right before crash)
    decision_landed = engine.evaluate_resume_decision(
        session_id=session_id,
        current_workspace_fingerprint="new_persisted_hash",
    )
    assert decision_landed.can_resume is True
    assert decision_landed.recommended_action == ToolActionRecoveryKind.SKIP_AND_REUSE
    assert decision_landed.divergence_detected is True
    assert "跳过重复写入" in decision_landed.prompt_instructions

    # Scenario B: Disk fingerprint unchanged (crashed before disk write)
    decision_unlanded = engine.evaluate_resume_decision(
        session_id=session_id,
        current_workspace_fingerprint="initial_hash",
    )
    assert decision_unlanded.can_resume is True
    assert decision_unlanded.recommended_action == ToolActionRecoveryKind.RE_EXECUTE
    assert decision_unlanded.divergence_detected is False
    assert "重新发起幂等写入" in decision_unlanded.prompt_instructions


def test_on_disk_atomic_persistence_and_reload() -> None:
    """Verifies that atomic on-disk persistence reliably survives process restart simulation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        config = SessionCheckpointConfig(storage_dir=temp_dir)
        engine1 = SessionStateAtomicResumeEngine(config=config)
        session_id = "sess_disk_persist"

        engine1.start_step(
            session_id=session_id,
            step_index=1,
            messages_count=2,
            workspace_fingerprint="fp_disk_1",
        )
        engine1.begin_tool_invocation(
            session_id=session_id,
            step_index=1,
            tool_name="replace_file_content",
            call_id="call_patch_1",
            input_args={"path": "src/core.py"},
            workspace_fingerprint="fp_disk_1",
            messages_count=2,
        )

        # Confirm file was written to disk
        sess_dir = Path(temp_dir) / session_id
        json_files = list(sess_dir.glob("*.json"))
        assert len(json_files) == 2

        # Simulate process reboot: spin up brand new engine instance pointing to same dir
        storage2 = SessionCheckpointStorage(config=config)
        engine2 = SessionStateAtomicResumeEngine(storage=storage2, config=config)

        assert engine2.detect_interruption(session_id) is True
        latest = storage2.get_latest_checkpoint(session_id)
        assert latest is not None
        assert latest.status == CheckpointStepStatus.TOOL_INVOKING
        assert latest.pending_tool_call is not None
        assert latest.pending_tool_call.tool_name == "replace_file_content"

        history = engine2.list_history_checkpoints(session_id)
        assert len(history) == 2


def test_timeline_rewind_branching() -> None:
    """Verifies rewinding timeline back to a historical step and creating a branch marker."""
    engine = SessionStateAtomicResumeEngine()
    session_id = "sess_rewind_test"

    cp1 = engine.start_step(session_id, 1, 2, "fp_1")
    engine.commit_step(session_id, 1, "fp_1", 3)

    engine.start_step(session_id, 2, 4, "fp_2")
    engine.commit_step(session_id, 2, "fp_2", 5)

    history_before = engine.list_history_checkpoints(session_id)
    assert len(history_before) == 4

    # Rewind to step 1
    rewound_cp = engine.rewind_to_checkpoint(session_id, cp1.checkpoint_id)
    assert rewound_cp.step_index == 1
    assert rewound_cp.metadata.get("rewound_from") == cp1.checkpoint_id

    history_after = engine.list_history_checkpoints(session_id)
    assert len(history_after) == 5
    assert history_after[-1].checkpoint_id == rewound_cp.checkpoint_id
