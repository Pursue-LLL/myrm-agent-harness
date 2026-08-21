"""Tests for execution state consistency validator and auto-reconciliation."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
from myrm_agent_harness.agent.context_management.strategies.summary.execution_state_validator import (
    audit_execution_consistency,
    normalize_file_path,
    reconcile_summary_execution_state,
)
from myrm_agent_harness.agent.context_management.strategies.summary.summary_auditor import (
    audit_summary,
    build_retry_guidance,
)
from myrm_agent_harness.agent.context_management.tracking.artifact_tracker import (
    ArtifactAction,
    ArtifactTracker,
    clear_artifact_tracker,
    create_artifact_tracker,
)


def test_normalize_file_path() -> None:
    """Test path normalization across various relative and Windows-style paths."""
    assert normalize_file_path("./src/auth/login.py") == "src/auth/login.py"
    assert normalize_file_path("src/auth/login.py") == "src/auth/login.py"
    assert normalize_file_path("src\\auth\\login.py") == "src/auth/login.py"
    assert normalize_file_path("/src/auth/login.py") == "src/auth/login.py"
    assert normalize_file_path("") == ""


def test_audit_execution_consistency_detects_hallucinations_and_missing() -> None:
    """Verify that hallucinated files and missing physical files are audited cleanly."""
    chat_id = "test_chat_consistency_1"
    tracker = create_artifact_tracker(chat_id)
    try:
        # Physical record: only auth.py was modified, test.py was created, doc.md was only read
        tracker.record("src/auth.py", ArtifactAction.MODIFIED)
        tracker.record("tests/test_auth.py", ArtifactAction.CREATED)
        tracker.record("docs/readme.md", ArtifactAction.READ)

        # Summary claims auth.py was modified, but also hallucinates config.yaml, and misses tests/test_auth.py
        summary = StructuredSummary(
            user_goal="Refactor authentication and test suite thoroughly",
            completed_actions=["Modified auth.py", "Updated config.yaml"],
            last_action="Done",
            files_modified=["src/auth.py", "config.yaml"],
        )

        res = audit_execution_consistency(summary, chat_id=chat_id)
        assert res.passed is False
        assert "config.yaml" in res.hallucinated_files
        assert any("tests/test_auth.py" in f for f in res.missing_files)
        assert len(res.issues) == 2
    finally:
        clear_artifact_tracker(chat_id)


def test_reconcile_summary_execution_state_auto_heals_files() -> None:
    """Verify that reconcile_summary_execution_state cleans hallucinations and injects missing files."""
    chat_id = "test_chat_reconcile_2"
    tracker = create_artifact_tracker(chat_id)
    try:
        tracker.record("src/auth.py", ArtifactAction.MODIFIED)
        tracker.record("src/utils.py", ArtifactAction.CREATED)

        summary = StructuredSummary(
            user_goal="Refactor auth",
            completed_actions=["Updated auth.py"],
            last_action="Done",
            files_modified=["src/auth.py", "hallucinated_db.py"],
        )

        healed = reconcile_summary_execution_state(summary, chat_id=chat_id)
        # hallucinated_db.py should be removed, src/utils.py should be injected
        assert "hallucinated_db.py" not in healed.files_modified
        assert "src/auth.py" in healed.files_modified
        assert "src/utils.py" in healed.files_modified
        assert len(healed.files_modified) == 2
    finally:
        clear_artifact_tracker(chat_id)


def test_summary_auditor_gate_with_execution_state_and_retry_guidance() -> None:
    """Verify that SummaryAuditor triggers gate failure on hallucinated files and generates retry guidance."""
    chat_id = "test_chat_auditor_3"
    tracker = create_artifact_tracker(chat_id)
    try:
        tracker.record("app/main.py", ArtifactAction.MODIFIED)

        messages = [
            HumanMessage(content="Please refactor app/main.py and fix the router bug"),
            AIMessage(content="Refactoring main.py"),
            ToolMessage(content="OK", name="file_edit_tool", tool_call_id="call_1"),
        ]

        summary = StructuredSummary(
            user_goal="Please refactor app/main.py and fix the router bug",
            completed_actions=["Refactored app/main.py"],
            last_action="Finished",
            files_modified=["app/main.py", "app/bogus_file.py"],
        )

        audit_res = audit_summary(summary, messages, chat_id=chat_id)
        assert audit_res.passed is False
        assert "app/bogus_file.py" in audit_res.hallucinated_files

        guidance = build_retry_guidance(audit_res)
        assert "Do NOT claim these files were modified" in guidance
        assert "app/bogus_file.py" in guidance
    finally:
        clear_artifact_tracker(chat_id)


def test_execution_consistency_graceful_fallback_without_tracker() -> None:
    """Verify that when no tracker exists (e.g. pure in-memory test), consistency check gracefully passes."""
    summary = StructuredSummary(
        user_goal="Valid goal with sufficient length",
        completed_actions=["Valid action"],
        last_action="Done",
        files_modified=["some_file.py"],
    )

    res = audit_execution_consistency(summary, chat_id=None)
    assert res.passed is True
    assert len(res.issues) == 0

    healed = reconcile_summary_execution_state(summary, chat_id=None)
    assert healed.files_modified == ["some_file.py"]
