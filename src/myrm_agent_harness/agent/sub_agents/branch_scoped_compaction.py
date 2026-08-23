"""Branch-scoped subagent artifact and structured summary compaction merger.

Implements scoped compaction merge across subagent execution branches:
- Gathers physical disk mutations (ArtifactTracker) from all child subagents spawned under a session.
- Merges structured handover states (completed actions, findings, pending tasks, relevant files)
  from completed/active subagents into the parent agent's StructuredSummary without extra LLM calls.
- Preserves prompt cache safety by mutating only in-memory dataclass fields before injection into HumanMessage.

[INPUT]
- manager::ACTIVE_SUBAGENTS, ACTIVE_SUBAGENT_SESSIONS, COMPLETED_SUBAGENT_RESULTS (POS: Subagent registries)
- session_tree::_session_id_candidates (POS: Session ID normalization)
- tracking.artifact_tracker::get_artifact_tracker, ArtifactAction (POS: Physical artifact events)
- infra.schemas::StructuredSummary (POS: Core summary dataclass)

[OUTPUT]
- collect_subagent_branch_trackers: list of ArtifactTracker instances for all subagents under a session
- merge_subagent_branch_artifacts: set of normalized file paths modified by subagents
- merge_subagent_handovers_into_summary: pure deterministic merger enriching StructuredSummary with child outcomes

[POS]
Harness subagent branch compaction merger. Pure deterministic heuristics, zero LLM calls.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
from myrm_agent_harness.agent.context_management.tracking.artifact_tracker import (
    ArtifactAction,
    ArtifactTracker,
    get_artifact_tracker,
)
from myrm_agent_harness.agent.sub_agents.manager import (
    ACTIVE_SUBAGENT_SESSIONS,
    ACTIVE_SUBAGENTS,
    COMPLETED_SUBAGENT_RESULTS,
)
from myrm_agent_harness.agent.sub_agents.session_tree import _session_id_candidates
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    pass

logger = get_agent_logger(__name__)


def collect_subagent_task_ids_for_session(session_id: str) -> list[str]:
    """Find all active and completed subagent task_ids associated with a session."""
    if not session_id:
        return []
    candidates = _session_id_candidates(session_id)
    if not candidates:
        return []

    task_ids: list[str] = []
    seen: set[str] = set()

    # 1. From completed results registry
    for task_id, (candidate_session, _completed_at, _row) in COMPLETED_SUBAGENT_RESULTS.items():
        if candidate_session in candidates and task_id not in seen:
            task_ids.append(task_id)
            seen.add(task_id)

    # 2. From active sessions registry
    for task_id, candidate_session in ACTIVE_SUBAGENT_SESSIONS.items():
        if candidate_session in candidates and task_id not in seen:
            task_ids.append(task_id)
            seen.add(task_id)

    # 3. From active manager instances
    for task_id, manager in ACTIVE_SUBAGENTS.items():
        if task_id in seen:
            continue
        mapped = ACTIVE_SUBAGENT_SESSIONS.get(task_id, "").strip()
        if mapped in candidates:
            task_ids.append(task_id)
            seen.add(task_id)
            continue
        parent = getattr(manager, "_parent_agent", None)
        parent_sid = str(getattr(parent, "session_id", "") or "").strip()
        if parent_sid in candidates:
            task_ids.append(task_id)
            seen.add(task_id)

    return task_ids


def collect_subagent_branch_trackers(session_id: str) -> list[ArtifactTracker]:
    """Retrieve all ArtifactTracker instances associated with child subagent sessions."""
    task_ids = collect_subagent_task_ids_for_session(session_id)
    trackers: list[ArtifactTracker] = []
    for tid in task_ids:
        # Check direct task_id tracker, subagent_task_id tracker, and child session trackers
        candidates = [tid, f"subagent_{tid}", f"child_{tid}"]
        for c in candidates:
            t = get_artifact_tracker(c)
            if t is not None and t not in trackers:
                trackers.append(t)
    return trackers


def merge_subagent_branch_artifacts(session_id: str) -> set[str]:
    """Extract authoritative set of modified/created files from all child subagents."""
    sub_files: set[str] = set()
    trackers = collect_subagent_branch_trackers(session_id)
    for tracker in trackers:
        for record in tracker.records:
            if record.action in (ArtifactAction.CREATED, ArtifactAction.MODIFIED):
                cleaned = record.path.strip().replace("\\", "/")
                norm = os.path.normpath(cleaned).replace("\\", "/")
                if norm:
                    sub_files.add(norm)

    # Also collect from completed subagent handover_state.relevant_files
    candidates = _session_id_candidates(session_id) if session_id else set()
    for task_id, (candidate_session, _completed_at, row) in COMPLETED_SUBAGENT_RESULTS.items():
        if candidate_session not in candidates:
            continue
        handover = row.get("handover_state")
        if isinstance(handover, dict):
            relevant_files = handover.get("relevant_files")
            if isinstance(relevant_files, list):
                for rf in relevant_files:
                    if isinstance(rf, str) and rf.strip():
                        cleaned = rf.strip().replace("\\", "/")
                        norm = os.path.normpath(cleaned).replace("\\", "/")
                        if norm:
                            sub_files.add(norm)

    return sub_files


def merge_subagent_handovers_into_summary(
    summary: StructuredSummary,
    session_id: str | None,
) -> StructuredSummary:
    """Enrich parent StructuredSummary with completed child subagents' outcomes.

    - Appends subagent completed actions to completed_actions.
    - Appends subagent key discoveries / risks to key_findings / errors_and_fixes.
    - Appends subagent pending todos to pending_user_asks.
    - Merges relevant files into files_modified.
    - Deduplicates entries while preserving insertion order.
    """
    if not session_id:
        return summary

    candidates = _session_id_candidates(session_id)
    if not candidates:
        return summary

    new_actions: list[str] = list(summary.completed_actions)
    new_findings: list[str] = list(summary.key_findings)
    new_errors: list[str] = list(summary.errors_and_fixes)
    new_pending: list[str] = list(summary.pending_user_asks)
    new_files: list[str] = list(summary.files_modified)

    seen_actions: set[str] = set(new_actions)
    seen_findings: set[str] = set(new_findings)
    seen_errors: set[str] = set(new_errors)
    seen_pending: set[str] = set(new_pending)
    seen_files: set[str] = set(new_files)

    for task_id, (candidate_session, _completed_at, row) in COMPLETED_SUBAGENT_RESULTS.items():
        if candidate_session not in candidates:
            continue

        agent_type = str(row.get("agent_type", "subagent"))
        status = str(row.get("status", ""))
        handover = row.get("handover_state")

        # Extract actions from handover or result
        if isinstance(handover, dict):
            completed = handover.get("task_completed")
            if isinstance(completed, list):
                for item in completed:
                    if isinstance(item, str) and item.strip():
                        entry = f"[{agent_type}] {item.strip()}"
                        if entry not in seen_actions:
                            new_actions.append(entry)
                            seen_actions.add(entry)

            todos = handover.get("pending_todos")
            if isinstance(todos, list):
                for item in todos:
                    if isinstance(item, str) and item.strip():
                        entry = f"[{agent_type} pending] {item.strip()}"
                        if entry not in seen_pending:
                            new_pending.append(entry)
                            seen_pending.add(entry)

            risks = handover.get("risks_or_notes")
            if isinstance(risks, list):
                for item in risks:
                    if isinstance(item, str) and item.strip():
                        entry = f"[{agent_type} risk/note] {item.strip()}"
                        if entry not in seen_findings:
                            new_findings.append(entry)
                            seen_findings.add(entry)

            rel_files = handover.get("relevant_files")
            if isinstance(rel_files, list):
                for item in rel_files:
                    if isinstance(item, str) and item.strip():
                        fpath = item.strip()
                        if fpath not in seen_files:
                            new_files.append(fpath)
                            seen_files.add(fpath)
        else:
            # Fallback if no structured handover
            result_text = str(row.get("result", "")).strip()
            if status == "completed" and result_text:
                preview = result_text.splitlines()[0][:120]
                entry = f"[{agent_type}] Completed: {preview}"
                if entry not in seen_actions:
                    new_actions.append(entry)
                    seen_actions.add(entry)
            elif status == "failed":
                err_text = str(row.get("error", "")).strip() or "Task failed"
                entry = f"[{agent_type} error] {err_text[:120]}"
                if entry not in seen_errors:
                    new_errors.append(entry)
                    seen_errors.add(entry)

    summary.completed_actions = new_actions
    summary.key_findings = new_findings
    summary.errors_and_fixes = new_errors
    summary.pending_user_asks = new_pending
    summary.files_modified = new_files

    return summary
