"""Quarantine manager and audit reporter for toxic memory passages.

Isolates flagged passages to prevent prompt injection and generates structured
audit records for forensic traceability.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

from .types import (
    MemoryPassageUnit,
    PassageScreeningVerdict,
    PassageVerdictStatus,
    QuarantinedPassageReport,
)


class PassageQuarantineManager:
    """Manages passage isolation and audit telemetry generation."""

    def __init__(self, max_history_records: int = 500) -> None:
        self.max_history_records = max_history_records
        self._quarantine_archive: list[QuarantinedPassageReport] = []

    def filter_and_quarantine(
        self,
        passages: Sequence[MemoryPassageUnit],
        verdicts: Sequence[PassageScreeningVerdict],
    ) -> tuple[list[MemoryPassageUnit], list[QuarantinedPassageReport]]:
        """Filter out toxic passages and produce quarantine audit reports for flagged items."""
        verdict_map: dict[str, PassageScreeningVerdict] = {v.passage_id: v for v in verdicts}
        clean_passages: list[MemoryPassageUnit] = []
        reports: list[QuarantinedPassageReport] = []
        now_iso = datetime.datetime.now(datetime.UTC).isoformat()

        for passage in passages:
            verdict = verdict_map.get(passage.passage_id)
            if verdict is None or verdict.status != PassageVerdictStatus.TOXIC:
                clean_passages.append(passage)
                continue

            threat_cat = (
                verdict.matched_patterns[0].pattern_category
                if verdict.matched_patterns
                else "remote_model_score_threshold"
            )
            report = QuarantinedPassageReport(
                passage_id=passage.passage_id,
                source_uri=passage.source_uri,
                snippet=passage.content[:120].strip(),
                rejection_reason=verdict.rejection_reason,
                pathway_used=verdict.pathway,
                threat_category=threat_cat,
                detected_at=now_iso,
            )
            reports.append(report)
            self._quarantine_archive.append(report)

        # Enforce memory archive bound
        if len(self._quarantine_archive) > self.max_history_records:
            self._quarantine_archive = self._quarantine_archive[-self.max_history_records :]

        return clean_passages, reports

    def get_quarantined_records(self, limit: int = 50) -> list[QuarantinedPassageReport]:
        """Return recently quarantined passage reports."""
        return list(reversed(self._quarantine_archive[-limit:]))
