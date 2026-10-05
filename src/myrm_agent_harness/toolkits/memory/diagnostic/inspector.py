"""Automated Memory Diagnostic and Root Cause Inspector Coordinator."""

from .models import (
    MemoryDiagnosticProbeContext,
    MemoryDiagnosticReport,
)
from .tree import FiveStepDiagnosticDecisionTree


class AutomatedMemoryDiagnosticInspector:
    """Orchestrates 5-step diagnostic probes and generates standardized health certificates."""

    def __init__(
        self,
        decision_tree: FiveStepDiagnosticDecisionTree | None = None,
    ) -> None:
        """Initialize inspector with diagnostic decision tree."""
        self._tree = decision_tree or FiveStepDiagnosticDecisionTree()
        self._historical_reports: list[MemoryDiagnosticReport] = []

    @property
    def total_inspections_conducted(self) -> int:
        """Return count of completed diagnostic inspections."""
        return len(self._historical_reports)

    def inspect(
        self,
        context: MemoryDiagnosticProbeContext,
        session_exists: bool = True,
        is_session_active: bool = True,
        found_in_store: bool = True,
        found_in_pending: bool = False,
        is_superseded: bool = False,
        is_expired: bool = False,
        scope_matched: bool = True,
        scope_details: str | None = None,
        retrieved_rank: int | None = 1,
        token_budget_exceeded: bool = False,
        model_cited: bool = True,
    ) -> MemoryDiagnosticReport:
        """Execute automated root cause diagnosis for a suspected memory failure.

        Args:
            context: Diagnostic context parameters.
            session_exists: Whether session metadata exists in store.
            is_session_active: Whether session is currently active and valid.
            found_in_store: Whether fact was extracted into persistent store.
            found_in_pending: Whether fact is queued in pending approval.
            is_superseded: Whether fact was updated or invalidated by newer information.
            is_expired: Whether fact has passed its TTL temporal expiration.
            scope_matched: Whether query scope aligns with stored memory scope.
            scope_details: Diagnostic detail regarding scope comparison.
            retrieved_rank: Final recall ranking position (None if not recalled).
            token_budget_exceeded: Whether context budget forced truncation of this fact.
            model_cited: Whether the model explicitly referenced this fact in output.

        Returns:
            Structured MemoryDiagnosticReport with conclusive root cause.
        """
        report = self._tree.evaluate(
            context=context,
            session_exists=session_exists,
            is_session_active=is_session_active,
            found_in_store=found_in_store,
            found_in_pending=found_in_pending,
            is_superseded=is_superseded,
            is_expired=is_expired,
            scope_matched=scope_matched,
            scope_details=scope_details,
            retrieved_rank=retrieved_rank,
            token_budget_exceeded=token_budget_exceeded,
            model_cited=model_cited,
        )
        self._historical_reports.append(report)
        return report

    def list_reports(
        self,
        session_id: str | None = None,
    ) -> list[MemoryDiagnosticReport]:
        """List historical diagnostic certificates, optionally filtered by session."""
        if session_id is None:
            return list(self._historical_reports)
        return [r for r in self._historical_reports if r.session_id == session_id]
