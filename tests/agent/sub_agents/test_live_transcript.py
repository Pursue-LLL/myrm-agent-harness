# -*- coding: utf-8 -*-
"""Unit tests for Subagent Live Transcript, Persistent Delegation Ledger, and Smart Approvals."""

import os
import tempfile
import pytest

from myrm_agent_harness.agent.sub_agents.live_transcript import (
    ApprovalDecision,
    DelegationTaskRecord,
    MoAReasoningEffortGovernor,
    PersistentDelegationLedger,
    ReasoningEffortLevel,
    SmartApprovalGate,
    SubagentLiveTranscriptEmitter,
    SubagentTranscriptEvent,
    TaskDelegationStatus,
    TranscriptEventKind,
)


def test_live_transcript_emitter_basic_and_subscribers() -> None:
    emitter = SubagentLiveTranscriptEmitter()
    received_task_events: list[SubagentTranscriptEvent] = []
    received_global_events: list[SubagentTranscriptEvent] = []

    emitter.subscribe("task-001", lambda e: received_task_events.append(e))
    emitter.subscribe(None, lambda e: received_global_events.append(e))

    ev1 = emitter.emit(
        task_id="task-001",
        subagent_id="sub-arch",
        kind=TranscriptEventKind.THOUGHT,
        human_readable="Analyzing codebase modularity",
        payload={"step": 1},
    )
    assert ev1.seq == 1
    assert ev1.task_id == "task-001"
    assert ev1.kind == TranscriptEventKind.THOUGHT

    ev2 = emitter.emit(
        task_id="task-001",
        subagent_id="sub-arch",
        kind=TranscriptEventKind.TOOL_CALL,
        human_readable="Calling view_file",
        payload={"file": "types.py"},
    )
    assert ev2.seq == 2

    # Verify subscribers received both events
    assert len(received_task_events) == 2
    assert len(received_global_events) == 2

    # Query events
    events = emitter.get_events("task-001")
    assert len(events) == 2
    paged = emitter.get_events("task-001", after_seq=1)
    assert len(paged) == 1
    assert paged[0].seq == 2


def test_live_transcript_payload_truncation() -> None:
    emitter = SubagentLiveTranscriptEmitter()
    huge_str = "x" * 5000
    ev = emitter.emit(
        task_id="task-002",
        subagent_id="sub-retriever",
        kind=TranscriptEventKind.TOOL_RESULT,
        human_readable="Tool output received",
        payload={"raw_output": huge_str},
    )
    val = ev.payload.get("raw_output")
    assert isinstance(val, str)
    assert "[TRUNCATED]" in val
    assert len(val) < 2200


def test_persistent_delegation_ledger_lifecycle_and_disk() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_file = os.path.join(tmpdir, "ledger.json")
        ledger = PersistentDelegationLedger(storage_path=storage_file)

        # 1. Register task
        task = ledger.register_task(
            task_id="task-100",
            session_id="session-alpha",
            subagent_id="sub-worker",
            role="researcher",
            prompt="Analyze competitors",
            reasoning_effort=ReasoningEffortLevel.MEDIUM,
        )
        assert task.status == TaskDelegationStatus.PENDING
        assert task.task_id == "task-100"

        # 2. Update status to RUNNING
        running_task = ledger.update_status("task-100", TaskDelegationStatus.RUNNING)
        assert running_task is not None
        assert running_task.status == TaskDelegationStatus.RUNNING

        # 3. Checkpoint
        ckp_task = ledger.save_checkpoint(
            "task-100",
            checkpoint_step=3,
            artifacts=[{"name": "competitors.json", "uri": "/tmp/comp.json"}],
        )
        assert ckp_task is not None
        assert ckp_task.checkpoint_step == 3
        assert len(ckp_task.artifacts) == 1

        # 4. Verify disk persistence across restart
        new_ledger = PersistentDelegationLedger(storage_path=storage_file)
        reloaded_task = new_ledger.get_task("task-100")
        assert reloaded_task is not None
        assert reloaded_task.checkpoint_step == 3
        assert reloaded_task.status == TaskDelegationStatus.RUNNING

        # 5. Complete task
        completed = new_ledger.update_status(
            "task-100",
            TaskDelegationStatus.COMPLETED,
            summary="Competitor analysis done successfully",
        )
        assert completed is not None
        assert completed.status == TaskDelegationStatus.COMPLETED
        assert completed.finished_at is not None
        assert completed.summary == "Competitor analysis done successfully"


def test_delegation_ledger_orphan_recovery() -> None:
    ledger = PersistentDelegationLedger()
    ledger.register_task(
        task_id="task-active",
        session_id="sess-1",
        subagent_id="sub-1",
        role="worker",
        prompt="Active job",
    )
    ledger.update_status("task-active", TaskDelegationStatus.RUNNING)

    ledger.register_task(
        task_id="task-pending",
        session_id="sess-1",
        subagent_id="sub-2",
        role="worker",
        prompt="Pending job",
    )

    ledger.register_task(
        task_id="task-done",
        session_id="sess-1",
        subagent_id="sub-3",
        role="worker",
        prompt="Finished job",
    )
    ledger.update_status("task-done", TaskDelegationStatus.COMPLETED)

    # Recover orphans
    recovered = ledger.recover_orphaned_tasks()
    assert len(recovered) == 2
    recovered_ids = {r.task_id for r in recovered}
    assert recovered_ids == {"task-active", "task-pending"}

    for r in recovered:
        assert r.status == TaskDelegationStatus.PAUSED
        assert "auto-recovered" in (r.error_message or "")

    done_task = ledger.get_task("task-done")
    assert done_task is not None
    assert done_task.status == TaskDelegationStatus.COMPLETED


def test_smart_approvals_risk_and_single_use() -> None:
    gate = SmartApprovalGate()

    # 1. Dangerous command evaluation
    req = gate.evaluate_command("task-99", "sub-exec", "rm -rf /tmp/test_dir")
    assert req.risk_score >= 0.9
    assert any("Destructive" in r for r in req.risk_reasons)

    # 2. Approve command
    res = gate.resolve_approval(req.approval_id, ApprovalDecision.APPROVED)
    assert res is not None
    assert res.decision == ApprovalDecision.APPROVED

    # 3. First consumption succeeds
    assert gate.consume_approval(req.approval_id) is True

    # 4. Second consumption fails (single-use bounding)
    assert gate.consume_approval(req.approval_id) is False


def test_smart_approvals_custom_deny_and_interactive_feedback() -> None:
    gate = SmartApprovalGate(custom_deny_rules=[r"\bDROP\s+DATABASE\b"])

    # Match custom rule
    req = gate.evaluate_command("task-99", "sub-db", "DROP DATABASE production;")
    assert req.risk_score == 1.0
    assert any("mandatory user deny rule" in r for r in req.risk_reasons)

    # Resolve with interactive user /deny reason
    res = gate.resolve_approval(
        req.approval_id,
        ApprovalDecision.DENIED,
        deny_reason="Production database drop is strictly forbidden by company compliance.",
    )
    assert res is not None
    assert res.decision == ApprovalDecision.DENIED
    assert res.deny_reason is not None
    assert "remediation_prompt" in res.model_dump()
    assert res.remediation_prompt is not None
    assert "company compliance" in res.remediation_prompt
    assert "DROP DATABASE" in res.remediation_prompt


def test_moa_reasoning_effort_governor() -> None:
    governor = MoAReasoningEffortGovernor()

    assert governor.resolve_effort("triage") == ReasoningEffortLevel.LOW
    assert governor.resolve_effort("retriever") == ReasoningEffortLevel.MEDIUM
    assert governor.resolve_effort("architect") == ReasoningEffortLevel.MAX
    assert governor.resolve_effort("deep_reasoner") == ReasoningEffortLevel.ULTRA

    # Custom override
    governor.set_role_effort("custom_scout", ReasoningEffortLevel.MAX)
    assert governor.resolve_effort("custom_scout") == ReasoningEffortLevel.MAX

    # Token budgets
    assert governor.get_token_budget(ReasoningEffortLevel.LOW) == 1024
    assert governor.get_token_budget(ReasoningEffortLevel.ULTRA) == 32768

    # Usage tracking
    c1 = governor.record_usage("task-moa-1", 500)
    c2 = governor.record_usage("task-moa-1", 700)
    assert c1 == 500
    assert c2 == 1200
    assert governor.get_cumulative_usage("task-moa-1") == 1200
