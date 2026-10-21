"""
[INPUT]: Raw execution spans, OpenTelemetry span attributes, and active skill context bindings.
[OUTPUT]: ActiveSkillSpanProcessor injecting myrm.skill.active attributes and aggregating per-skill telemetry.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/active_skill_telemetry/processor.py
"""

import threading
import time
from typing import Dict, List, Optional
from uuid import uuid4

from .context import get_active_skill
from .models import (
    ActiveSkillTelemetryReport,
    SkillSpanRecord,
    SkillTelemetryAggregation,
)

ACTIVE_SKILL_ATTRIBUTE_KEY = "myrm.skill.active"
COMPAT_SKILL_ATTRIBUTE_KEY = "omnigent.skill.active"


class ActiveSkillSpanProcessor:
    """Thread-safe telemetry processor injecting active skill tags and aggregating span performance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: List[SkillSpanRecord] = []

    def on_span_start(self, attributes: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Inject active skill attribute into span attributes dictionary on start if present in ContextVar."""
        attrs = dict(attributes) if attributes else {}
        current_skill = get_active_skill()
        if current_skill and ACTIVE_SKILL_ATTRIBUTE_KEY not in attrs:
            attrs[ACTIVE_SKILL_ATTRIBUTE_KEY] = current_skill
            attrs[COMPAT_SKILL_ATTRIBUTE_KEY] = current_skill
        return attrs

    def record_span(
        self,
        name: str,
        duration_ms: float,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        active_skill: Optional[str] = None,
        status: str = "ok",
        attributes: Optional[Dict[str, str]] = None,
        timestamp_ms: Optional[int] = None,
    ) -> SkillSpanRecord:
        """Record an execution span, automatically correlating with ContextVar active skill if not specified."""
        attrs = dict(attributes) if attributes else {}
        resolved_skill = active_skill or get_active_skill() or attrs.get(ACTIVE_SKILL_ATTRIBUTE_KEY)

        if resolved_skill:
            attrs[ACTIVE_SKILL_ATTRIBUTE_KEY] = resolved_skill
            attrs[COMPAT_SKILL_ATTRIBUTE_KEY] = resolved_skill

        record = SkillSpanRecord(
            span_id=span_id or f"span-{uuid4().hex[:12]}",
            trace_id=trace_id or f"trace-{uuid4().hex[:12]}",
            name=name,
            active_skill=resolved_skill,
            duration_ms=max(0.0, float(duration_ms)),
            status=status.lower(),
            attributes=attrs,
            timestamp_ms=timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
        )

        with self._lock:
            self._records.append(record)

        return record

    def get_spans(self, skill_name: Optional[str] = None) -> List[SkillSpanRecord]:
        """Retrieve recorded spans with optional filtering by active skill."""
        with self._lock:
            records = list(self._records)

        if skill_name:
            records = [r for r in records if r.active_skill == skill_name]

        return records

    def get_report(self) -> ActiveSkillTelemetryReport:
        """Generate full observability report aggregating P95 latency and error rate partitioned by skill."""
        with self._lock:
            records = list(self._records)

        unattributed_count = sum(1 for r in records if not r.active_skill)
        skill_groups: Dict[str, List[SkillSpanRecord]] = {}

        for r in records:
            if r.active_skill:
                if r.active_skill not in skill_groups:
                    skill_groups[r.active_skill] = []
                skill_groups[r.active_skill].append(r)

        aggregations: List[SkillTelemetryAggregation] = []
        for skill, spans in skill_groups.items():
            total = len(spans)
            errors = sum(1 for s in spans if s.status == "error")
            durations = sorted(s.duration_ms for s in spans)
            avg_dur = sum(durations) / total if total > 0 else 0.0

            p95_idx = min(int(0.95 * total), total - 1)
            p95_dur = durations[p95_idx] if total > 0 else 0.0

            aggregations.append(
                SkillTelemetryAggregation(
                    skill_name=skill,
                    total_spans=total,
                    error_spans=errors,
                    error_rate=round(errors / total, 4) if total > 0 else 0.0,
                    avg_duration_ms=round(avg_dur, 2),
                    p95_duration_ms=round(p95_dur, 2),
                )
            )

        # Sort aggregations by total spans descending
        aggregations.sort(key=lambda a: a.total_spans, reverse=True)

        return ActiveSkillTelemetryReport(
            total_spans_recorded=len(records),
            skills_count=len(skill_groups),
            skill_aggregations=aggregations,
            unattributed_spans_count=unattributed_count,
            timestamp_ms=int(time.time() * 1000),
        )

    def reset(self) -> None:
        """Clear recorded spans for test isolation."""
        with self._lock:
            self._records.clear()
