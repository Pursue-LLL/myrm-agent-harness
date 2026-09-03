"""Unit tests for Structured Handoff Schema SSOT and Leaf Isolation Policy."""

from __future__ import annotations

from myrm_agent_harness.agent.parallel.summary import batch_summary, inject_capacity_signal
from myrm_agent_harness.agent.sub_agents.builder import _HANDOVER_PROTOCOL_PROMPT
from myrm_agent_harness.agent.sub_agents.executor_helpers import _parse_handover_state
from myrm_agent_harness.agent.sub_agents.handover import AgentHandoverState, HandoffFinding
from myrm_agent_harness.agent.sub_agents.notifications import format_notification
from myrm_agent_harness.agent.sub_agents.types import (
    DELEGATION_CAPABILITY_MANIFEST,
    DelegationCapabilityManifest,
    SubAgentResult,
    SubAgentStatus,
)


def test_delegation_manifest_leaf_blocks_cron_manage_tool() -> None:
    manifest = DelegationCapabilityManifest.default()
    assert "cron_manage_tool" in manifest.leaf_blocked_tools
    assert "cron_manage_tool" in DELEGATION_CAPABILITY_MANIFEST.leaf_blocked_tools


def test_handoff_finding_dataclass_and_serialization() -> None:
    finding = HandoffFinding(
        finding="High memory consumption in worker pool",
        evidence="metrics.log:42 - 1.2GB allocated",
        confidence="high",
    )
    d = finding.to_dict()
    assert d == {
        "finding": "High memory consumption in worker pool",
        "evidence": "metrics.log:42 - 1.2GB allocated",
        "confidence": "high",
    }
    restored = HandoffFinding.from_dict(d)
    assert restored == finding


def test_agent_handover_state_extended_fields_roundtrip() -> None:
    state = AgentHandoverState(
        summary="Completed performance benchmarking on database engines.",
        findings=[
            HandoffFinding(
                finding="Engine Qdrant achieved 4.2ms latency",
                evidence="benchmark_run.json:15",
                confidence="high",
            ),
        ],
        citations=["https://qdrant.tech/docs/benchmarks/"],
        artifact_refs=["vault://benchmarks/qdrant_report.md"],
        context_artifacts=["vault://schemas/dataset_v1.json"],
        task_completed=["Setup testbed", "Run 100k queries benchmark"],
        pending_todos=["Run comparative analysis against Milvus"],
        risks_or_notes=["Ensure memory limit is capped at 2GB on low-tier VMs"],
        relevant_files=["scripts/benchmarks/run.py", "configs/qdrant.yaml"],
    )

    data = state.to_dict()
    assert data["summary"] == "Completed performance benchmarking on database engines."
    findings = data["findings"]
    assert isinstance(findings, list)
    assert len(findings) == 1
    first_finding = findings[0]
    assert isinstance(first_finding, dict)
    assert first_finding["finding"] == "Engine Qdrant achieved 4.2ms latency"
    assert data["citations"] == ["https://qdrant.tech/docs/benchmarks/"]
    assert data["artifact_refs"] == ["vault://benchmarks/qdrant_report.md"]
    assert data["context_artifacts"] == ["vault://schemas/dataset_v1.json"]
    task_completed = data["task_completed"]
    assert isinstance(task_completed, list)
    assert len(task_completed) == 2

    restored = AgentHandoverState.from_dict(data)
    assert restored.summary == state.summary
    assert len(restored.findings) == 1
    assert restored.findings[0] == state.findings[0]
    assert restored.citations == state.citations
    assert restored.artifact_refs == state.artifact_refs
    assert restored.context_artifacts == state.context_artifacts
    assert restored.task_completed == state.task_completed


def test_parse_handover_state_xml_block_with_extended_fields() -> None:
    raw = """
Task execution finished successfully.
<handover>
{
  "summary": "Refactored auth module to use strict tokens.",
  "findings": [
    {"finding": "Legacy cookie auth is deprecated", "evidence": "auth/session.py:10", "confidence": "high"},
    "Plain string finding fallback"
  ],
  "citations": ["https://oauth.net/2/"],
  "artifact_refs": ["vault://auth_patch.diff"],
  "context_artifacts": ["configs/auth_jwt.json"],
  "task_completed": ["Token generator implemented", "Expired token revocation added"],
  "pending_todos": ["Add unit tests for refresh endpoint"],
  "risks_or_notes": ["Requires JWT_SECRET environment variable"],
  "relevant_files": ["app/auth/tokens.py"]
}
</handover>
End of execution.
"""
    parsed = _parse_handover_state(raw, "task_123")
    assert parsed is not None
    assert parsed.summary == "Refactored auth module to use strict tokens."
    assert len(parsed.findings) == 2
    assert parsed.findings[0].finding == "Legacy cookie auth is deprecated"
    assert parsed.findings[0].evidence == "auth/session.py:10"
    assert parsed.findings[1].finding == "Plain string finding fallback"
    assert parsed.citations == ["https://oauth.net/2/"]
    assert parsed.artifact_refs == ["vault://auth_patch.diff"]
    assert parsed.context_artifacts == ["configs/auth_jwt.json"]
    assert parsed.task_completed == ["Token generator implemented", "Expired token revocation added"]
    assert parsed.pending_todos == ["Add unit tests for refresh endpoint"]


def test_parse_handover_state_unclosed_tag_or_markdown_fence() -> None:
    raw = """
<handover>
```json
{
  "summary": "Unclosed tag with fence test",
  "task_completed": ["Step 1 done"]
}
"""
    parsed = _parse_handover_state(raw, "task_unclosed")
    assert parsed is not None
    assert parsed.summary == "Unclosed tag with fence test"
    assert parsed.task_completed == ["Step 1 done"]


def test_parse_handover_state_key_fallback_recovery() -> None:
    raw = """
Here is the JSON handover without XML tags:
```json
{
  "summary": "Fallback key discovery",
  "artifact_refs": ["vault://generated_output.txt"],
  "task_completed": ["Item A"]
}
```
"""
    parsed = _parse_handover_state(raw, "task_fallback")
    assert parsed is not None
    assert parsed.summary == "Fallback key discovery"
    assert parsed.artifact_refs == ["vault://generated_output.txt"]


def test_handover_protocol_prompt_contains_all_schema_keys() -> None:
    for key in (
        "summary",
        "findings",
        "citations",
        "artifact_refs",
        "context_artifacts",
        "task_completed",
        "pending_todos",
        "risks_or_notes",
        "relevant_files",
    ):
        assert f'"{key}"' in _HANDOVER_PROTOCOL_PROMPT


def test_batch_summary_aggregates_structured_handoff() -> None:
    subagent_results = [
        {
            "success": True,
            "task_id": "sub_1",
            "agent_type": "security_scanner",
            "handover_state": {
                "summary": "Worker 1 done",
                "findings": [{"finding": "Finding 1", "evidence": "file1.py:1", "confidence": "high"}],
                "artifact_refs": ["vault://ref1.md"],
                "citations": ["https://example.com/cwe-89", "https://example.com/shared"],
            },
        },
        {
            "success": True,
            "task_id": "sub_2",
            "agent_type": "linter",
            "handover_state": {
                "summary": "Worker 2 done",
                "findings": [{"finding": "Finding 2", "evidence": "file2.py:2", "confidence": "medium"}],
                "artifact_refs": ["vault://ref2.md"],
                "citations": ["https://example.com/shared", "https://example.com/pep8"],
            },
        },
        {
            "success": False,
            "task_id": "sub_3",
            "error": "Timeout",
        },
    ]

    summary = batch_summary(subagent_results)
    assert summary["success"] is False
    assert summary["status"] == "partial_success"
    assert summary["total_count"] == 3
    assert summary["completed_count"] == 2
    assert summary["failed_count"] == 1
    assert "handoff_states" in summary
    handoff_states = summary["handoff_states"]
    assert isinstance(handoff_states, list)
    assert len(handoff_states) == 2
    assert summary["all_artifact_refs"] == ["vault://ref1.md", "vault://ref2.md"]
    assert summary["all_citations"] == [
        "https://example.com/cwe-89",
        "https://example.com/shared",
        "https://example.com/pep8",
    ]
    all_findings = summary["all_findings"]
    assert isinstance(all_findings, list)
    assert len(all_findings) == 2
    assert all_findings[0]["source_task_id"] == "sub_1"
    assert all_findings[0]["agent_type"] == "security_scanner"
    assert all_findings[1]["source_task_id"] == "sub_2"
    assert all_findings[1]["agent_type"] == "linter"


def test_handoff_finding_confidence_normalization() -> None:
    f1 = HandoffFinding.from_dict({"finding": "A", "confidence": "HIGH"})
    assert f1.confidence == "high"

    f2 = HandoffFinding.from_dict({"finding": "B", "confidence": " Medium "})
    assert f2.confidence == "medium"

    f3 = HandoffFinding.from_dict({"finding": "C", "confidence": "low"})
    assert f3.confidence == "low"

    f4 = HandoffFinding.from_dict({"finding": "D", "confidence": "invalid_value"})
    assert f4.confidence == "high"


def test_format_notification_prioritizes_handover_summary_and_findings() -> None:
    result = SubAgentResult(
        success=True,
        task_id="task_audit_1",
        agent_type="security_reviewer",
        result="Long verbose transcript with 50 tool logs and 3000 chars of debug output...",
        duration_seconds=3.2,
        status=SubAgentStatus.COMPLETED,
        handover_state=AgentHandoverState(
            summary="Found 1 SQL injection vulnerability in user login path.",
            findings=[
                HandoffFinding(
                    finding="Unsanitized input in query",
                    evidence="auth/login.py:42",
                    confidence="high",
                ),
            ],
            artifact_refs=["vault://reports/audit_2026.md"],
            citations=["https://cwe.mitre.org/data/definitions/89.html"],
            task_completed=["Static AST scan", "Taint analysis"],
            risks_or_notes=["Needs immediate patch before release"],
        ),
    )

    notif = format_notification(result)
    assert "[Subagent 'security_reviewer' (task_id=task_audit_1) completed successfully] (3.2s)" in notif
    assert "Summary:\nFound 1 SQL injection vulnerability in user login path." in notif
    assert "Result:" not in notif
    assert "Key Findings:\n - [HIGH] Unsanitized input in query (evidence: auth/login.py:42)" in notif
    assert "Citations:\n - https://cwe.mitre.org/data/definitions/89.html" in notif
    assert "Artifacts:\n - vault://reports/audit_2026.md" in notif
    assert "Completed:\n - Static AST scan\n - Taint analysis" in notif
    assert "Risks:\n - Needs immediate patch before release" in notif


def test_format_notification_fallback_without_summary() -> None:
    result = SubAgentResult(
        success=True,
        task_id="task_calc_1",
        agent_type="calculator",
        result="42",
        status=SubAgentStatus.COMPLETED,
        handover_state=AgentHandoverState(
            task_completed=["compute 6 * 7"],
        ),
    )

    notif = format_notification(result)
    assert "Result:\n42" in notif
    assert "Summary:" not in notif
    assert "Completed:\n - compute 6 * 7" in notif


def test_inject_capacity_signal_success_and_exception() -> None:
    from unittest.mock import MagicMock

    parent = MagicMock()
    snap = MagicMock()
    snap.active_children = 2
    snap.max_children = 5
    snap.remaining_slots = 3
    snap.spawned_descendants = 4
    snap.max_descendants = 10
    snap.remaining_descendants = 6
    parent._subagent_manager.get_capacity_snapshot.return_value = snap

    res = inject_capacity_signal({"success": True}, parent)
    assert "system_state" in res
    assert res["system_state"] == {
        "active_subagents": "2/5",
        "remaining_slots": 3,
        "descendants_spawned": "4/10",
        "remaining_descendants": 6,
    }

    # Exception path fallback
    broken_parent = MagicMock()
    broken_parent._subagent_manager.get_capacity_snapshot.side_effect = RuntimeError("unavailable")
    fallback_res = inject_capacity_signal({"success": True}, broken_parent)
    assert "system_state" not in fallback_res


def test_batch_summary_status_branches_and_failure_reasons() -> None:
    # All failure
    all_failed = [
        {"success": False, "error": "ConnectionRefused"},
        {"success": False, "reason": "ResourceExhausted"},
        {"success": False},  # triggers "unknown_failure" fallback
    ]
    summary_failed = batch_summary(all_failed)
    assert summary_failed["success"] is False
    assert summary_failed["status"] == "failed"
    assert summary_failed["completed_count"] == 0
    assert summary_failed["failed_count"] == 3
    assert summary_failed["failure_reasons"] == ["ConnectionRefused", "ResourceExhausted", "unknown_failure"]
    assert summary_failed["partial_success"] is False

    # All success without handover
    all_success = [
        {"success": True, "result": "ok 1"},
        {"success": True, "result": "ok 2"},
    ]
    summary_success = batch_summary(all_success)
    assert summary_success["success"] is True
    assert summary_success["status"] == "completed"
    assert summary_success["completed_count"] == 2
    assert summary_success["failed_count"] == 0
    assert summary_success["partial_success"] is False
    assert "handoff_states" not in summary_success
    assert "all_artifact_refs" not in summary_success
    assert "all_citations" not in summary_success
    assert "all_findings" not in summary_success



