"""Collector and metric calculation engine for approval false positives.

[INPUT]
- Classifier decisions, user review feedback, evaluation timestamps.

[OUTPUT]
- ClassifierVerdictLog records, FalsePositiveRateMetric metrics, FalsePositiveSample tuning exports.

[POS]
- Harness core security module collecting verdict telemetry and computing empirical false positive rates.
"""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.core.security.approval_metrics.types import (
    ClassifierDecision,
    ClassifierVerdictLog,
    FalsePositiveRateMetric,
    FalsePositiveSample,
    FeedbackOutcome,
)


class ApprovalMetricCollector:
    """Manages classifier verdict telemetry, calculates FPR, and aggregates tuning samples."""

    def __init__(self, default_alert_threshold: float = 0.05) -> None:
        self._verdicts: dict[str, ClassifierVerdictLog] = {}
        self._default_alert_threshold = default_alert_threshold

    def record_verdict(
        self,
        command: str,
        decision: ClassifierDecision,
        reason: str,
        workspace_root: str | None = None,
        taint_labels: list[str] | None = None,
        timestamp: float | None = None,
        audit_id: str | None = None,
    ) -> ClassifierVerdictLog:
        """Record an immutable classifier decision log."""
        now = timestamp if timestamp is not None else time.time()
        aid = audit_id or f"verdict-{int(now * 1000)}-{uuid.uuid4().hex[:8]}"

        log_entry = ClassifierVerdictLog(
            audit_id=aid,
            timestamp=now,
            command=command,
            decision=decision,
            reason=reason,
            workspace_root=workspace_root,
            taint_labels=list(taint_labels or []),
            feedback=FeedbackOutcome.UNREVIEWED,
            feedback_reason=None,
            reviewed_at=None,
        )
        self._verdicts[aid] = log_entry
        return log_entry

    def submit_feedback(
        self,
        audit_id: str,
        feedback: FeedbackOutcome,
        feedback_reason: str,
        reviewed_at: float | None = None,
    ) -> bool:
        """Submit ground-truth human feedback on a classifier verdict."""
        existing = self._verdicts.get(audit_id)
        if existing is None:
            return False

        now = reviewed_at if reviewed_at is not None else time.time()
        updated = ClassifierVerdictLog(
            audit_id=existing.audit_id,
            timestamp=existing.timestamp,
            command=existing.command,
            decision=existing.decision,
            reason=existing.reason,
            workspace_root=existing.workspace_root,
            taint_labels=existing.taint_labels,
            feedback=feedback,
            feedback_reason=feedback_reason,
            reviewed_at=now,
        )
        self._verdicts[audit_id] = updated
        return True

    def get_verdict(self, audit_id: str) -> ClassifierVerdictLog | None:
        """Retrieve a recorded verdict log by its audit identifier."""
        return self._verdicts.get(audit_id)

    def calculate_metrics(
        self,
        window_seconds: float = 86400.0,
        alert_threshold: float | None = None,
        current_time: float | None = None,
    ) -> FalsePositiveRateMetric:
        """Calculate false positive rates across sliding evaluation window."""
        now = current_time if current_time is not None else time.time()
        cutoff = now - window_seconds
        threshold = (
            alert_threshold
            if alert_threshold is not None
            else self._default_alert_threshold
        )

        in_window = [
            v for v in self._verdicts.values() if v.timestamp >= cutoff
        ]
        total_evaluations = len(in_window)

        blocks_or_asks = [
            v
            for v in in_window
            if v.decision
            in (ClassifierDecision.DENY, ClassifierDecision.UNCERTAIN)
        ]
        total_blocks_or_asks = len(blocks_or_asks)

        false_positives = [
            v
            for v in blocks_or_asks
            if v.feedback
            in (FeedbackOutcome.FALSE_POSITIVE, FeedbackOutcome.CONFIRMED_SAFE)
        ]
        confirmed_fps = len(false_positives)

        true_positives = [
            v
            for v in blocks_or_asks
            if v.feedback == FeedbackOutcome.TRUE_POSITIVE
        ]
        confirmed_tps = len(true_positives)

        # FPR relative to total blocked/interrupted actions
        fpr = (
            float(confirmed_fps) / float(total_blocks_or_asks)
            if total_blocks_or_asks > 0
            else 0.0
        )
        is_alerting = fpr > threshold and confirmed_fps > 0

        return FalsePositiveRateMetric(
            window_seconds=window_seconds,
            total_evaluations=total_evaluations,
            total_blocks_or_asks=total_blocks_or_asks,
            confirmed_false_positives=confirmed_fps,
            confirmed_true_positives=confirmed_tps,
            false_positive_rate=round(fpr, 4),
            alert_threshold=threshold,
            is_alerting=is_alerting,
        )

    def export_false_positive_samples(
        self,
        limit: int = 50,
    ) -> list[FalsePositiveSample]:
        """Aggregate confirmed false positives to refine ALLOW exceptions and BLOCK rules."""
        fp_entries = [
            v
            for v in self._verdicts.values()
            if v.feedback
            in (FeedbackOutcome.FALSE_POSITIVE, FeedbackOutcome.CONFIRMED_SAFE)
        ]
        # Sort descending by timestamp
        fp_entries.sort(key=lambda x: x.timestamp, reverse=True)

        samples: list[FalsePositiveSample] = []
        for entry in fp_entries[:limit]:
            cmd_snippet = (
                entry.command[:60] + "..."
                if len(entry.command) > 60
                else entry.command
            )
            suggested = (
                f"Add command pattern '{cmd_snippet}' to ALLOW EXCEPTIONS or narrow "
                f"BLAST RADIUS trigger for reason: '{entry.reason}'."
            )
            samples.append(
                FalsePositiveSample(
                    audit_id=entry.audit_id,
                    timestamp=entry.timestamp,
                    command=entry.command,
                    decision=entry.decision,
                    original_reason=entry.reason,
                    feedback_reason=entry.feedback_reason or "Overturned as safe by user",
                    suggested_rule_tuning=suggested,
                )
            )
        return samples

    def clear(self) -> None:
        """Clear all in-memory telemetry logs."""
        self._verdicts.clear()
