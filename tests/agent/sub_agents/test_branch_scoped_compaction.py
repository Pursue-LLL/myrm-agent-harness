"""Tests for branch-scoped subagent artifact and structured summary compaction merger."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
from myrm_agent_harness.agent.context_management.strategies.summary.execution_state_validator import (
    extract_physical_modified_files,
    reconcile_summary_execution_state,
)
from myrm_agent_harness.agent.context_management.tracking.artifact_tracker import (
    ArtifactAction,
    clear_artifact_tracker,
    create_artifact_tracker,
)
from myrm_agent_harness.agent.sub_agents.branch_scoped_compaction import (
    collect_subagent_branch_trackers,
    collect_subagent_task_ids_for_session,
    merge_subagent_branch_artifacts,
    merge_subagent_handovers_into_summary,
)
from myrm_agent_harness.agent.sub_agents.manager import (
    ACTIVE_SUBAGENT_SESSIONS,
    COMPLETED_SUBAGENT_RESULTS,
)


@pytest.fixture(autouse=True)
def cleanup_subagent_registries() -> None:
    COMPLETED_SUBAGENT_RESULTS.clear()
    ACTIVE_SUBAGENT_SESSIONS.clear()
    yield
    COMPLETED_SUBAGENT_RESULTS.clear()
    ACTIVE_SUBAGENT_SESSIONS.clear()


def test_collect_subagent_task_ids_for_session() -> None:
    session_id = "session_123"
    COMPLETED_SUBAGENT_RESULTS["task_done_1"] = (
        session_id,
        1000.0,
        {"status": "completed", "agent_type": "coder"},
    )
    ACTIVE_SUBAGENT_SESSIONS["task_active_2"] = session_id

    ids = collect_subagent_task_ids_for_session(session_id)
    assert "task_done_1" in ids
    assert "task_active_2" in ids


def test_merge_subagent_branch_artifacts() -> None:
    session_id = "session_artifacts_test"
    child_task_id = "child_task_abc"
    COMPLETED_SUBAGENT_RESULTS[child_task_id] = (
        session_id,
        1000.0,
        {
            "status": "completed",
            "agent_type": "coder",
            "handover_state": {
                "relevant_files": ["src/auth/token.py", "docs/auth.md"],
            },
        },
    )

    child_tracker = create_artifact_tracker(child_task_id)
    try:
        child_tracker.record("src/auth/jwt.py", ArtifactAction.MODIFIED)
        child_tracker.record("tests/test_jwt.py", ArtifactAction.CREATED)

        files = merge_subagent_branch_artifacts(session_id)
        assert "src/auth/jwt.py" in files
        assert "tests/test_jwt.py" in files
        assert "src/auth/token.py" in files
        assert "docs/auth.md" in files
    finally:
        clear_artifact_tracker(child_task_id)


def test_execution_state_validator_incorporates_branch_artifacts() -> None:
    session_id = "session_validator_test"
    child_task_id = "child_worker_1"

    COMPLETED_SUBAGENT_RESULTS[child_task_id] = (
        session_id,
        1000.0,
        {
            "status": "completed",
            "agent_type": "tester",
            "handover_state": {
                "relevant_files": ["tests/test_branch_merge.py"],
            },
        },
    )

    child_tracker = create_artifact_tracker(child_task_id)
    try:
        child_tracker.record("tests/test_branch_merge.py", ArtifactAction.CREATED)

        # Parent tracker is empty
        physical_files = extract_physical_modified_files(session_id)
        assert "tests/test_branch_merge.py" in physical_files

        summary = StructuredSummary(
            user_goal="Run branch test task",
            completed_actions=["Dispatched worker"],
            last_action="Done",
            files_modified=[],
        )

        reconciled = reconcile_summary_execution_state(summary, chat_id=session_id)
        assert "tests/test_branch_merge.py" in reconciled.files_modified
    finally:
        clear_artifact_tracker(child_task_id)


def test_merge_subagent_handovers_into_summary() -> None:
    session_id = "session_summary_merge_test"
    COMPLETED_SUBAGENT_RESULTS["task_coder"] = (
        session_id,
        1000.0,
        {
            "status": "completed",
            "agent_type": "coder",
            "handover_state": {
                "task_completed": ["Refactored token.py", "Added JWT verification"],
                "pending_todos": ["Add refresh token endpoint"],
                "risks_or_notes": ["Token expiry set to 15m"],
                "relevant_files": ["src/token.py"],
            },
        },
    )
    COMPLETED_SUBAGENT_RESULTS["task_failed_reviewer"] = (
        session_id,
        1005.0,
        {
            "status": "failed",
            "agent_type": "reviewer",
            "error": "SyntaxError in token.py",
        },
    )

    summary = StructuredSummary(
        user_goal="Complete auth refactor",
        completed_actions=["Spawned subagents"],
        last_action="Waiting",
        files_modified=["config.json"],
    )

    merged = merge_subagent_handovers_into_summary(summary, session_id)

    assert "[coder] Refactored token.py" in merged.completed_actions
    assert "[coder] Added JWT verification" in merged.completed_actions
    assert "[coder pending] Add refresh token endpoint" in merged.pending_user_asks
    assert "[coder risk/note] Token expiry set to 15m" in merged.key_findings
    assert "[reviewer error] SyntaxError in token.py" in merged.errors_and_fixes
    assert "src/token.py" in merged.files_modified
    assert "config.json" in merged.files_modified
