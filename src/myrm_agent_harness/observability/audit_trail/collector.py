"""Dual-Track Prior Audit Trail Collector.

[INPUT]
- types::(AuditTrailEntry, PriorAuditState, ComplianceOutcome, AuditSummaryStats, RuleTriggerHit)
- redactor::sanitize_sensitive_data

[OUTPUT]
- DualTrackAuditCollector: Thread-safe collector recording pre-act intent and completing post-act results

[POS]
Harness-level engine orchestrating fail-closed intent logging and policy trigger attribution.
"""

from __future__ import annotations

import collections
import threading
from datetime import datetime, timezone
from typing import Mapping, Sequence

from myrm_agent_harness.observability.audit_trail.redactor import sanitize_sensitive_data
from myrm_agent_harness.observability.audit_trail.types import (
    AuditSummaryStats,
    AuditTrailEntry,
    ComplianceOutcome,
    PriorAuditState,
    RuleTriggerHit,
)


class DualTrackAuditCollector:
    """In-memory thread-safe collector for dual-track prior audit trail logs."""

    def __init__(self, *, max_entries: int = 5000) -> None:
        self._max_entries = max(100, max_entries)
        self._lock = threading.Lock()
        self._entries: list[AuditTrailEntry] = []
        self._active_intents: dict[str, AuditTrailEntry] = {}

    def log_intent(
        self,
        *,
        session_id: str,
        agent_id: str,
        tool_name: str,
        intent_summary: str,
        proposed_args: Mapping[str, object] | None = None,
        rule_name: str = "DEFAULT_ALLOW",
        is_human_take_the_wheel: bool = False,
        entry_id: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> AuditTrailEntry:
        """Pre-act logging: records intent before execution begins (Fail-Closed compliance invariant)."""
        sanitized_args = sanitize_sensitive_data(proposed_args or {})
        sanitized_summary = sanitize_sensitive_data(intent_summary)

        entry = AuditTrailEntry(
            session_id=session_id,
            agent_id=agent_id,
            tool_name=tool_name,
            intent_summary=str(sanitized_summary),
            raw_intent_args=sanitized_args if isinstance(sanitized_args, Mapping) else {},
            rule_name=rule_name,
            state=PriorAuditState.INTENT_LOGGED,
            outcome=ComplianceOutcome.PERMITTED,
            is_human_take_the_wheel=is_human_take_the_wheel,
            entry_id=entry_id or AuditTrailEntry(session_id="", agent_id="", tool_name="", intent_summary="").entry_id,
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._active_intents[entry.entry_id] = entry
            self._entries.append(entry)
            if len(self._entries) > self._max_entries:
                self._entries.pop(0)

        return entry

    def complete_act(
        self,
        entry_id: str,
        *,
        latency_ms: float,
        output_length: int = 0,
        outcome: ComplianceOutcome = ComplianceOutcome.PERMITTED,
        error_message: str | None = None,
    ) -> AuditTrailEntry | None:
        """Post-act logging: pairs execution outcome with prior recorded intent."""
        sanitized_err = sanitize_sensitive_data(error_message) if error_message else None

        with self._lock:
            existing = self._active_intents.pop(entry_id, None)
            if existing is None:
                # Search back in historical entries
                for idx, item in enumerate(self._entries):
                    if item.entry_id == entry_id:
                        existing = item
                        break
                if existing is None:
                    return None

            completed_state = (
                PriorAuditState.COMPLETED
                if outcome == ComplianceOutcome.PERMITTED
                else PriorAuditState.FAILED
            )

            updated = AuditTrailEntry(
                entry_id=existing.entry_id,
                session_id=existing.session_id,
                agent_id=existing.agent_id,
                tool_name=existing.tool_name,
                intent_summary=existing.intent_summary,
                raw_intent_args=existing.raw_intent_args,
                rule_name=existing.rule_name,
                state=completed_state,
                outcome=outcome,
                is_human_take_the_wheel=existing.is_human_take_the_wheel,
                created_at=existing.created_at,
                completed_at=datetime.now(timezone.utc),
                latency_ms=round(max(0.0, latency_ms), 2),
                output_length=max(0, output_length),
                error_message=str(sanitized_err) if sanitized_err else None,
                metadata=existing.metadata,
            )

            # Replace in historical list
            for idx, item in enumerate(self._entries):
                if item.entry_id == entry_id:
                    self._entries[idx] = updated
                    break

            return updated

    def refuse_act(
        self,
        entry_id: str,
        *,
        reason: str,
        rule_name: str | None = None,
    ) -> AuditTrailEntry | None:
        """Mark a pre-logged intent as refused/blocked by security policy or user."""
        sanitized_reason = sanitize_sensitive_data(reason)

        with self._lock:
            existing = self._active_intents.pop(entry_id, None)
            if existing is None:
                for idx, item in enumerate(self._entries):
                    if item.entry_id == entry_id:
                        existing = item
                        break
                if existing is None:
                    return None

            refused_entry = AuditTrailEntry(
                entry_id=existing.entry_id,
                session_id=existing.session_id,
                agent_id=existing.agent_id,
                tool_name=existing.tool_name,
                intent_summary=existing.intent_summary,
                raw_intent_args=existing.raw_intent_args,
                rule_name=rule_name or existing.rule_name,
                state=PriorAuditState.REFUSED,
                outcome=ComplianceOutcome.REFUSED,
                is_human_take_the_wheel=existing.is_human_take_the_wheel,
                created_at=existing.created_at,
                completed_at=datetime.now(timezone.utc),
                latency_ms=0.0,
                output_length=0,
                error_message=str(sanitized_reason),
                metadata=existing.metadata,
            )

            for idx, item in enumerate(self._entries):
                if item.entry_id == entry_id:
                    self._entries[idx] = refused_entry
                    break

            return refused_entry

    def list_entries(
        self,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
        outcome: ComplianceOutcome | None = None,
        limit: int = 100,
    ) -> Sequence[AuditTrailEntry]:
        """Query collected audit trail entries with optional filtering."""
        with self._lock:
            res: list[AuditTrailEntry] = []
            for item in reversed(self._entries):
                if session_id and item.session_id != session_id:
                    continue
                if agent_id and item.agent_id != agent_id:
                    continue
                if outcome and item.outcome != outcome:
                    continue
                res.append(item)
                if len(res) >= limit:
                    break
            return res

    def get_summary_stats(
        self,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
    ) -> AuditSummaryStats:
        """Compute multi-dimensional summary statistics and rule trigger telemetry."""
        with self._lock:
            candidates = [
                e for e in self._entries
                if (not session_id or e.session_id == session_id)
                and (not agent_id or e.agent_id == agent_id)
            ]

        total = len(candidates)
        if total == 0:
            return AuditSummaryStats(
                total_entries=0,
                permitted_count=0,
                refused_count=0,
                failed_count=0,
                human_take_the_wheel_count=0,
                compliance_rate=1.0,
                avg_latency_ms=0.0,
                top_rules_triggered=[],
            )

        permitted = sum(1 for e in candidates if e.outcome == ComplianceOutcome.PERMITTED)
        refused = sum(1 for e in candidates if e.outcome == ComplianceOutcome.REFUSED)
        failed = sum(1 for e in candidates if e.outcome == ComplianceOutcome.FAILED)
        take_the_wheel = sum(1 for e in candidates if e.is_human_take_the_wheel)
        total_lat = sum(e.latency_ms for e in candidates if e.latency_ms > 0)
        lat_count = sum(1 for e in candidates if e.latency_ms > 0)
        avg_lat = round(total_lat / lat_count, 2) if lat_count > 0 else 0.0

        # Group by rule
        rule_groups: dict[str, list[AuditTrailEntry]] = collections.defaultdict(list)
        for e in candidates:
            rule_groups[e.rule_name].append(e)

        rule_hits: list[RuleTriggerHit] = []
        for rname, r_entries in rule_groups.items():
            r_total = len(r_entries)
            r_refused = sum(1 for e in r_entries if e.outcome == ComplianceOutcome.REFUSED)
            r_permitted = sum(1 for e in r_entries if e.outcome == ComplianceOutcome.PERMITTED)
            r_failed = sum(1 for e in r_entries if e.outcome == ComplianceOutcome.FAILED)
            r_rate = round(r_refused / r_total, 4) if r_total > 0 else 0.0
            samples = [e.intent_summary for e in r_entries[:3]]

            rule_hits.append(
                RuleTriggerHit(
                    rule_name=rname,
                    trigger_count=r_total,
                    refused_count=r_refused,
                    permitted_count=r_permitted,
                    failed_count=r_failed,
                    refusal_rate=r_rate,
                    sample_targets=samples,
                )
            )

        rule_hits.sort(key=lambda x: (x.refused_count, x.trigger_count), reverse=True)

        return AuditSummaryStats(
            total_entries=total,
            permitted_count=permitted,
            refused_count=refused,
            failed_count=failed,
            human_take_the_wheel_count=take_the_wheel,
            compliance_rate=round(permitted / total, 4),
            avg_latency_ms=avg_lat,
            top_rules_triggered=rule_hits,
        )

    def clear(self) -> None:
        """Clear collector state."""
        with self._lock:
            self._entries.clear()
            self._active_intents.clear()
