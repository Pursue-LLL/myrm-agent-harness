"""Causal triad past pitfall retrieval and version drift evaluator.

[POS]
Queries historical postmortems and discarded architectural decisions to extract
causal triads (approach -> pitfall -> validated alternative) with negative sentiment gating.

[INPUT]
- collections.abc.Sequence, collections.abc.Callable, collections.abc.Awaitable
- .models (DecisionIntent, PitfallTriadRecord, AlertSeverity)

[OUTPUT]
- PastPitfallRetriever, PitfallSourceFunc
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence

from myrm_agent_harness.toolkits.memory.pitfall_alert.models import (
    AlertSeverity,
    DecisionIntent,
    PitfallTriadRecord,
)

PitfallSourceFunc = Callable[[str], Awaitable[Sequence[PitfallTriadRecord]]]

# Critical negative lesson keywords required to avoid false alarm warnings
_NEGATIVE_MARKERS = [
    "死锁", "内存泄漏", "羊群效应", "性能瓶颈", "故障", "crash", "deadlock",
    "pitfall", "bottleneck", "踩坑", "事故", "阻塞", "oom", "timeout",
    "丢数据", "锁竞争", "高延迟", "穿透", "雪崩", "击穿", "panic",
]


class PastPitfallRetriever:
    """Retrieves causal triad postmortems matching decision intents."""

    def __init__(
        self,
        custom_provider: PitfallSourceFunc | None = None,
        min_relevance_score: float = 0.65,
    ) -> None:
        self._custom_provider = custom_provider
        self._min_relevance = min_relevance_score
        # Built-in in-memory fallback ledger of historical lessons
        self._in_memory_records: list[PitfallTriadRecord] = []

    def seed_records(self, records: Sequence[PitfallTriadRecord]) -> None:
        """Seed pre-existing historical postmortem records for testing or local indexing."""
        self._in_memory_records.extend(records)

    async def retrieve_matching_triads(
        self, intent: DecisionIntent
    ) -> list[PitfallTriadRecord]:
        """Query memory store for historical failures directly relevant to user's decision."""
        subject = intent.target_subject.lower()
        solution = intent.proposed_solution.lower()
        query_text = intent.raw_query.lower()

        candidates: list[PitfallTriadRecord] = []

        # 1. Query custom async provider if available
        if self._custom_provider is not None:
            try:
                external_records = await self._custom_provider(intent.target_subject)
                candidates.extend(external_records)
            except Exception:
                pass

        # 2. Add in-memory seeded records
        candidates.extend(self._in_memory_records)

        matched: list[PitfallTriadRecord] = []
        for rec in candidates:
            rec_subj = rec.subject.lower()
            rec_approach = rec.approach.lower()
            rec_lesson = rec.pitfall_lesson.lower()

            # Match criteria: subject match OR approach overlap
            subject_hit = (
                subject in rec_subj
                or rec_subj in subject
                or solution in rec_approach
                or rec_subj in query_text
            )
            if not subject_hit:
                continue

            # Strict negative marker gate: must exhibit explicit failure root cause
            has_negative = any(
                m in rec_lesson or m in rec.negative_markers for m in _NEGATIVE_MARKERS
            )
            if not has_negative:
                continue

            matched.append(rec)

        return matched

    def evaluate_drift_warning(
        self, record: PitfallTriadRecord, current_runtime_version: str = ""
    ) -> str:
        """Check if historical postmortem might be obsolete due to runtime evolution."""
        if not record.version_context:
            return ""

        hist_ver = record.version_context.lower()
        if not current_runtime_version:
            return f"注意: 该教训发生在环境 [{record.version_context}] 下，请结合当前技术版本实测验证。"

        curr_ver = current_runtime_version.lower()
        if hist_ver != curr_ver:
            return (
                f"⚠️ 环境演进提示: 历史踩坑发生于 [{record.version_context}]，"
                f"当前环境为 [{current_runtime_version}]，部分已知缺陷可能已被上游修复。"
            )
        return ""

    @staticmethod
    def create_triad(
        subject: str,
        approach: str,
        pitfall_lesson: str,
        validated_alternative: str,
        severity: AlertSeverity = AlertSeverity.WARNING,
        incident_date: str = "",
        version_context: str = "",
        source_id: str = "manual_postmortem",
    ) -> PitfallTriadRecord:
        """Factory helper creating validated causal triad records."""
        markers = [m for m in _NEGATIVE_MARKERS if m in pitfall_lesson.lower()]
        return PitfallTriadRecord(
            triad_id=f"triad-{uuid.uuid4().hex[:8]}",
            subject=subject,
            approach=approach,
            pitfall_lesson=pitfall_lesson,
            validated_alternative=validated_alternative,
            severity=severity,
            incident_date=incident_date,
            version_context=version_context,
            negative_markers=markers,
            source_id=source_id,
        )
