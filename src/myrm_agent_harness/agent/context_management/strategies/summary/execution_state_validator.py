"""Execution state physical consistency validator and reconciler.

Audits ``StructuredSummary`` output against immutable runtime execution records
(``ArtifactTracker`` file events and ``ToolMessage`` execution results) to eliminate
LLM hallucinations in summary fields (e.g. hallucinated files_modified or false-positive
completed_actions), and reconciles missing physical operations.

[INPUT]
- langchain_core.messages::BaseMessage, ToolMessage (POS: Message hierarchy)
- ...infra.schemas::StructuredSummary (POS: Core structured summary schema)
- ...tracking.artifact_tracker::ArtifactAction, ArtifactTracker, get_artifact_tracker (POS: Physical artifact tracker)

[OUTPUT]
- ExecutionConsistencyResult: dataclass capturing consistency pass/fail and discrepancy details
- audit_execution_consistency: pure audit function returning discrepancies
- reconcile_summary_execution_state: pure self-healing reconciliation function aligning summary with truth

[POS]
Quality gate & auto-reconciler for the summarizer subsystem. Pure deterministic heuristics, zero LLM calls.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage, ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ...infra.schemas import StructuredSummary
from ...tracking.artifact_tracker import ArtifactAction, get_artifact_tracker

logger = get_agent_logger(__name__)

_NORM_PATH_RE = re.compile(r"^[./\\]+")


def normalize_file_path(path: str) -> str:
    """Normalize file path for deterministic set comparison across platforms."""
    if not path:
        return ""
    cleaned = path.strip().replace("\\", "/")
    # Remove leading ./ or /
    cleaned = _NORM_PATH_RE.sub("", cleaned)
    return os.path.normpath(cleaned).replace("\\", "/")


@dataclass(frozen=True)
class ExecutionConsistencyResult:
    """Audit result for execution state consistency against physical artifacts."""

    passed: bool
    hallucinated_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    failed_action_warnings: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


_FILE_PATH_EXTRACT_RE = re.compile(
    r"(?:file_path|path|target|file|filename)[\"']?\s*[:=]\s*[`\"']?([^`\"'\s,]+)[`\"']?|"
    r"(?:written to|created|modified|saved|wrote)\s*:?\s*[`\"']?([^\s`\"',]+\.[a-zA-Z0-9_-]+)[`\"']?|"
    r"(?:file created|file modified|file saved)\s*:?\s*[`\"']?([^\s`\"',]+\.[a-zA-Z0-9_-]+)[`\"']?",
    re.IGNORECASE,
)


def extract_physical_modified_files(
    chat_id: str | None,
    messages: list[BaseMessage] | None = None,
) -> set[str]:
    """Extract authoritative set of modified/created files from ArtifactTracker and ToolMessages."""
    physical_files: set[str] = set()

    if chat_id:
        tracker = get_artifact_tracker(chat_id)
        if tracker:
            for record in tracker.records:
                if record.action in (ArtifactAction.CREATED, ArtifactAction.MODIFIED):
                    norm = normalize_file_path(record.path)
                    if norm:
                        physical_files.add(norm)

    if messages:
        # Secondary fallback / corroboration from ToolMessage metadata or write/edit tool calls
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_name = (msg.name or "").lower()
                if any(w in tool_name for w in ("write", "edit", "create", "save")):
                    # Check if error or success
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    if "error" not in content.lower() and "failed" not in content.lower():
                        # Extract path from artifact, additional_kwargs, or content
                        extracted_paths: list[str] = []
                        if getattr(msg, "artifact", None) and isinstance(msg.artifact, dict):
                            p = msg.artifact.get("path") or msg.artifact.get("file_path")
                            if isinstance(p, str):
                                extracted_paths.append(p)
                        if msg.additional_kwargs:
                            p = msg.additional_kwargs.get("path") or msg.additional_kwargs.get("file_path")
                            if isinstance(p, str):
                                extracted_paths.append(p)
                        for match in _FILE_PATH_EXTRACT_RE.findall(content):
                            for group in match:
                                if group:
                                    extracted_paths.append(group)
                        for raw_p in extracted_paths:
                            norm_p = normalize_file_path(raw_p)
                            if norm_p and "." in os.path.basename(norm_p):
                                physical_files.add(norm_p)

    return physical_files


def audit_execution_consistency(
    summary: StructuredSummary,
    chat_id: str | None,
    original_messages: list[BaseMessage] | None = None,
) -> ExecutionConsistencyResult:
    """Audit summary fields against physical execution records."""
    issues: list[str] = []
    hallucinated: list[str] = []
    missing: list[str] = []

    physical_files = extract_physical_modified_files(chat_id, original_messages)

    # Normalize summary files_modified
    summary_files_norm: dict[str, str] = {}
    for f in summary.files_modified:
        norm = normalize_file_path(f)
        if norm:
            summary_files_norm[norm] = f

    # If physical files exist in tracker, verify summary doesn't hallucinate non-existent files
    if physical_files:
        for norm_f, orig_f in summary_files_norm.items():
            if norm_f not in physical_files:
                # Check if partial basename matches to be lenient with subpaths
                matched = any(norm_f.endswith(pf) or pf.endswith(norm_f) for pf in physical_files)
                if not matched:
                    hallucinated.append(orig_f)
                    issues.append(f"files_modified claims '{orig_f}' but no physical write/create event occurred")

        for pf in sorted(physical_files):
            matched = any(pf == sn or sn.endswith(pf) or pf.endswith(sn) for sn in summary_files_norm)
            if not matched:
                missing.append(pf)
                issues.append(f"Physical file '{pf}' modified on disk but omitted from summary files_modified")

    passed = len(issues) == 0
    return ExecutionConsistencyResult(
        passed=passed,
        hallucinated_files=hallucinated,
        missing_files=missing,
        issues=issues,
    )


def reconcile_summary_execution_state(
    summary: StructuredSummary,
    chat_id: str | None,
    original_messages: list[BaseMessage] | None = None,
) -> StructuredSummary:
    """Reconcile summary fields with physical execution truth (Auto-Reconcile).

    - Removes hallucinated unwritten files from `files_modified`.
    - Injects missing on-disk modified files into `files_modified`.
    - Preserves deterministic ordering without altering other summary semantics.
    """
    if not chat_id:
        return summary

    tracker = get_artifact_tracker(chat_id)
    if not tracker:
        return summary

    physical_created_modified = {
        normalize_file_path(r.path): r.path
        for r in tracker.records
        if r.action in (ArtifactAction.CREATED, ArtifactAction.MODIFIED)
    }

    if not physical_created_modified and not summary.files_modified:
        return summary

    # Build curated files_modified set
    curated_files: list[str] = []
    seen_norm: set[str] = set()

    # 1. Keep valid claims from summary that match physical truth
    for raw_path in summary.files_modified:
        norm = normalize_file_path(raw_path)
        if norm in physical_created_modified:
            if norm not in seen_norm:
                curated_files.append(raw_path)
                seen_norm.add(norm)
        else:
            # Check suffix matching (e.g. relative vs absolute)
            matched_key = next(
                (pk for pk in physical_created_modified if norm.endswith(pk) or pk.endswith(norm)),
                None,
            )
            if matched_key:
                if matched_key not in seen_norm:
                    curated_files.append(raw_path)
                    seen_norm.add(matched_key)
            else:
                logger.debug(
                    "[ExecutionStateConsistency] Pruned hallucinated file '%s' from files_modified",
                    raw_path,
                )

    # 2. Add missing physical files from ArtifactTracker
    for norm_path, orig_path in sorted(physical_created_modified.items()):
        if norm_path not in seen_norm:
            curated_files.append(orig_path)
            seen_norm.add(norm_path)
            logger.debug(
                "[ExecutionStateConsistency] Injected missing physical file '%s' into files_modified",
                orig_path,
            )

    summary.files_modified = curated_files
    return summary
