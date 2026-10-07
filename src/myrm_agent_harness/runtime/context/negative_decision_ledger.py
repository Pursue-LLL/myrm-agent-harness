"""Engine for Negative Decision Ledger and Anti-Regression Protection.

Part of Item 129: NegativeDecisionAndRejectionReasonLedger.
Provides immutable tracking of disqualified approaches, persistent failure rationale,
protected uncompressible prompt constraints, and pre-flight plan interception.

[INPUT]
- runtime.context.negative_decision_ledger_types::AntiRegressionInterceptionResult, FailureRootCauseKind,
  NegativeDecisionEntry (POS: Types and models for Negative Decision Ledger and Anti-Regression Protection.)

[OUTPUT]
- NegativeDecisionLedger: Thread-safe append-only ledger managing rejected solutions and anti-regression
  guards.

[POS]
Engine for Negative Decision Ledger and Anti-Regression Protection.
"""

from __future__ import annotations

import datetime
import logging
import re
import threading
import uuid

from myrm_agent_harness.runtime.context.negative_decision_ledger_types import (
    AntiRegressionInterceptionResult,
    FailureRootCauseKind,
    NegativeDecisionEntry,
)

logger = logging.getLogger(__name__)


class NegativeDecisionLedger:
    """Thread-safe append-only ledger managing rejected solutions and anti-regression guards."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[NegativeDecisionEntry] = []

    def record_rejection(
        self,
        session_id: str,
        attempted_solution: str,
        root_cause_kind: FailureRootCauseKind,
        rejection_reason: str,
        associated_files: list[str] | None = None,
        disqualified_patterns: list[str] | None = None,
        tried_turn: int = 0,
    ) -> NegativeDecisionEntry:
        """Record a rejected or failed solution attempt in the ledger."""
        entry = NegativeDecisionEntry(
            entry_id=f"neg-{uuid.uuid4().hex[:10]}",
            session_id=session_id,
            attempted_solution=attempted_solution.strip(),
            root_cause_kind=root_cause_kind,
            rejection_reason=rejection_reason.strip(),
            associated_files=list(associated_files or []),
            disqualified_patterns=list(disqualified_patterns or []),
            tried_turn=max(0, tried_turn),
            timestamp_iso=datetime.datetime.now(datetime.UTC).isoformat(),
        )
        with self._lock:
            self._entries.append(entry)
        logger.info(
            "Recorded negative decision %s for session %s (cause: %s)",
            entry.entry_id,
            session_id,
            root_cause_kind.value,
        )
        return entry

    def get_entries(self, session_id: str | None = None) -> list[NegativeDecisionEntry]:
        """Retrieve negative decision entries optionally filtered by session."""
        with self._lock:
            if session_id is None:
                return list(self._entries)
            return [e for e in self._entries if e.session_id == session_id]

    def compile_protected_negative_constraints(self, session_id: str | None = None) -> str:
        """Compile immutable, uncompressible markdown block for prompt injection."""
        entries = self.get_entries(session_id=session_id)
        if not entries:
            return ""

        lines: list[str] = [
            "<forbidden_anti_regression_constraints>",
            "# Inviolable Negative Constraints (Previously Disqualified Approaches)",
            "The following approaches have already been attempted and failed or were explicitly rejected.",
            "DO NOT RETRY these solutions under any circumstances:\n",
        ]

        for idx, e in enumerate(entries, 1):
            lines.append(f"### {idx}. {e.attempted_solution}")
            lines.append(f"- **Root Cause**: `{e.root_cause_kind.value}`")
            lines.append(f"- **Failure / Rejection Reason**: {e.rejection_reason}")
            if e.associated_files:
                files_str = ", ".join(f"`{f}`" for f in e.associated_files)
                lines.append(f"- **Associated Files**: {files_str}")
            if e.disqualified_patterns:
                patterns_str = ", ".join(f"`{p}`" for p in e.disqualified_patterns)
                lines.append(f"- **Disqualified Patterns / Libraries**: {patterns_str}")
            lines.append("")

        lines.append("</forbidden_anti_regression_constraints>")
        return "\n".join(lines)

    def check_plan_regression(
        self,
        proposed_plan: str,
        target_files: list[str] | None = None,
        session_id: str | None = None,
    ) -> AntiRegressionInterceptionResult:
        """Pre-flight check verifying proposed plan does not re-attempt disqualified solutions."""
        entries = self.get_entries(session_id=session_id)
        if not entries:
            return AntiRegressionInterceptionResult(is_blocked=False)

        lower_plan = proposed_plan.lower()
        plan_files = set(target_files or [])

        for entry in entries:
            # 1. Check prohibited patterns
            for pattern in entry.disqualified_patterns:
                lower_pat = pattern.lower().strip()
                if not lower_pat:
                    continue
                if lower_pat in lower_plan or re.search(r"\b" + re.escape(lower_pat) + r"\b", lower_plan):
                    return AntiRegressionInterceptionResult(
                        is_blocked=True,
                        matched_entry=entry,
                        reason=(
                            f"Plan contains disqualified pattern '{pattern}' which failed previously "
                            f"(Root Cause: {entry.root_cause_kind.value}). Reason: {entry.rejection_reason}"
                        ),
                        alternative_suggestion=f"Avoid using '{pattern}'. Seek alternative architectures.",
                    )

            # 2. Check solution keywords overlap combined with overlapping target files
            sol_tokens = [t for t in re.findall(r"\w+", entry.attempted_solution.lower()) if len(t) > 2]
            if sol_tokens:
                overlap_count = sum(1 for tok in sol_tokens if tok in lower_plan)
                is_semantic_match = overlap_count >= max(2, len(sol_tokens) // 2)

                files_overlap = bool(plan_files.intersection(set(entry.associated_files)))
                if is_semantic_match and (files_overlap or not entry.associated_files):
                    return AntiRegressionInterceptionResult(
                        is_blocked=True,
                        matched_entry=entry,
                        reason=(
                            f"Plan re-attempts previously failed solution '{entry.attempted_solution}'. "
                            f"Failure Reason: {entry.rejection_reason}"
                        ),
                        alternative_suggestion="Review previous negative decisions and formulate a new approach.",
                    )

        return AntiRegressionInterceptionResult(is_blocked=False)
