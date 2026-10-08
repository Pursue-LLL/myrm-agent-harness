"""Structured Risk Audit Ledger for persistent compliance tracking.

[INPUT]
- ActionProposal, RiskEvaluationReport

[OUTPUT]
- StructuredRiskAuditLedger: thread-safe queryable ledger of evaluated proposals and outcomes.

[POS]
Harness core security subsystem. Maintains audit trail of risk assessments,
enabling non-repudiable post-mortem analysis and regulatory compliance.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from myrm_agent_harness.core.security.risk_evaluator.types import (
    ActionProposal,
    RiskEvaluationReport,
    RiskEvaluationTier,
)


@dataclass(frozen=True, slots=True)
class RiskAuditEntry:
    """Immutable entry in the risk audit ledger."""

    entry_id: str
    proposal: ActionProposal
    report: RiskEvaluationReport
    outcome: str  # approved, rejected, executed, aborted
    recorded_at: float = field(default_factory=time.time)


class StructuredRiskAuditLedger:
    """Thread-safe ledger recording all proposal evaluations and risk audit records."""

    def __init__(self, capacity: int = 1000) -> None:
        if capacity <= 0:
            raise ValueError("Audit ledger capacity must be positive")
        self._capacity = capacity
        self._entries: deque[RiskAuditEntry] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        """Maximum number of records in memory."""
        return self._capacity

    def record_entry(
        self,
        entry_id: str,
        proposal: ActionProposal,
        report: RiskEvaluationReport,
        outcome: str = "evaluated",
    ) -> RiskAuditEntry:
        """Append an evaluation result to the audit ledger."""
        entry = RiskAuditEntry(
            entry_id=entry_id,
            proposal=proposal,
            report=report,
            outcome=outcome,
            recorded_at=time.time(),
        )
        with self._lock:
            self._entries.append(entry)
        return entry

    def list_entries(
        self,
        tier: RiskEvaluationTier | None = None,
        limit: int = 100,
    ) -> list[RiskAuditEntry]:
        """Query recent entries in reverse chronological order with optional tier filter."""
        with self._lock:
            all_entries = list(self._entries)
        all_entries.reverse()

        if tier is not None:
            all_entries = [e for e in all_entries if e.report.tier == tier]

        return all_entries[:limit]

    def get_by_proposal_id(self, proposal_id: str) -> list[RiskAuditEntry]:
        """Fetch all audit entries related to a specific proposal ID."""
        with self._lock:
            return [e for e in self._entries if e.proposal.proposal_id == proposal_id]

    def clear(self) -> None:
        """Clear all records from ledger."""
        with self._lock:
            self._entries.clear()
