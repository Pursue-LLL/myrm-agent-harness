"""Memory retrieval post-fetch injection screening and dual-path degradation gate suite.

Exports the high-level screening suite, dual-path gate, and quarantine manager.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .dual_path_gate import DualPathDegradationGate
from .pattern_scanner import scan_passage_patterns
from .quarantine_manager import PassageQuarantineManager
from .types import (
    MemoryPassageUnit,
    MemoryScreeningBatchResult,
    MemoryScreeningPolicy,
    PassageScreeningVerdict,
    PassageVerdictStatus,
    PatternMatchDetail,
    QuarantinedPassageReport,
    ScreeningPathMode,
)


class MemoryRetrievalPostFetchScreeningSuite:
    """Industrial-grade post-fetch screening gate for long-term memory retrieval."""

    def __init__(
        self,
        policy: MemoryScreeningPolicy | None = None,
        remote_scorer: Callable[[str], float] | None = None,
    ) -> None:
        self.policy = policy or MemoryScreeningPolicy()
        self.gate = DualPathDegradationGate(policy=self.policy, remote_scorer=remote_scorer)
        self.quarantine_manager = PassageQuarantineManager()

    def screen_retrieved_passages(
        self,
        passages: list[MemoryPassageUnit],
    ) -> MemoryScreeningBatchResult:
        """Screen retrieved candidate passages before LLM prompt injection.

        Filters out toxic injection candidates and logs quarantine reports.
        """
        start_time = time.perf_counter()

        if not passages:
            latency = (time.perf_counter() - start_time) * 1000.0
            return MemoryScreeningBatchResult(
                total_evaluated=0,
                clean_passages=[],
                quarantined_reports=[],
                pathway_taken=ScreeningPathMode.NONE,
                latency_ms=latency,
                degradation_reason="empty_passages",
            )

        verdicts, pathway_taken, degradation_note = self.gate.evaluate_batch(passages)

        clean_passages, quarantine_reports = self.quarantine_manager.filter_and_quarantine(
            passages=passages,
            verdicts=verdicts,
        )

        latency = (time.perf_counter() - start_time) * 1000.0
        return MemoryScreeningBatchResult(
            total_evaluated=len(passages),
            clean_passages=clean_passages,
            quarantined_reports=quarantine_reports,
            pathway_taken=pathway_taken,
            latency_ms=latency,
            degradation_reason=degradation_note,
        )

    def get_quarantine_records(self, limit: int = 50) -> list[QuarantinedPassageReport]:
        """Fetch historical quarantined passage reports."""
        return self.quarantine_manager.get_quarantined_records(limit=limit)


__all__ = [
    "DualPathDegradationGate",
    "MemoryPassageUnit",
    "MemoryRetrievalPostFetchScreeningSuite",
    "MemoryScreeningBatchResult",
    "MemoryScreeningPolicy",
    "PassageQuarantineManager",
    "PassageScreeningVerdict",
    "PassageVerdictStatus",
    "PatternMatchDetail",
    "QuarantinedPassageReport",
    "ScreeningPathMode",
    "scan_passage_patterns",
]
