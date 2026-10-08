"""Core proactive pitfall alert and decision assist engine.

[POS]
Orchestrates shadow intent recognition, causal triad retrieval, session mute management,
and dual-channel alert dispatching (UI callouts vs. shadow prompt guidance).

[INPUT]
- time, uuid
- .models (AlertSeverity, DecisionIntentLevel, DispatchChannel, PitfallAlertCard, PitfallEvaluationReport)
- .intent_recognizer.ShadowDecisionIntentRecognizer
- .retriever.PastPitfallRetriever

[OUTPUT]
- ProactivePitfallAlertEngine
"""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.toolkits.memory.pitfall_alert.intent_recognizer import (
    ShadowDecisionIntentRecognizer,
)
from myrm_agent_harness.toolkits.memory.pitfall_alert.models import (
    AlertSeverity,
    DecisionIntentLevel,
    DispatchChannel,
    PitfallAlertCard,
    PitfallEvaluationReport,
)
from myrm_agent_harness.toolkits.memory.pitfall_alert.retriever import (
    PastPitfallRetriever,
)


class ProactivePitfallAlertEngine:
    """Coordinates real-time decision sniffing, historical lesson retrieval, and alert generation."""

    def __init__(
        self,
        intent_recognizer: ShadowDecisionIntentRecognizer | None = None,
        retriever: PastPitfallRetriever | None = None,
    ) -> None:
        self._recognizer = intent_recognizer or ShadowDecisionIntentRecognizer()
        self._retriever = retriever or PastPitfallRetriever()
        # session_id -> set of muted technical subjects
        self._muted_by_session: dict[str, set[str]] = {}

    @property
    def retriever(self) -> PastPitfallRetriever:
        return self._retriever

    def mute_subject(self, session_id: str, subject: str) -> None:
        """Mute future proactive alerts for a specific technical subject within a session."""
        if session_id not in self._muted_by_session:
            self._muted_by_session[session_id] = set()
        self._muted_by_session[session_id].add(subject.lower())

    def unmute_subject(self, session_id: str, subject: str) -> None:
        """Unmute previously suppressed alerts for a technical subject."""
        if session_id in self._muted_by_session:
            self._muted_by_session[session_id].discard(subject.lower())

    def is_subject_muted(self, session_id: str, subject: str) -> bool:
        """Check whether a technical subject is muted in the specified session."""
        return subject.lower() in self._muted_by_session.get(session_id, set())

    async def evaluate_input(
        self,
        user_input: str,
        session_id: str = "default",
        current_runtime_version: str = "",
    ) -> tuple[PitfallAlertCard | None, PitfallEvaluationReport]:
        """Evaluate input for decision commitment, match historical pitfalls, and dispatch alerts."""
        start_time = time.perf_counter()
        eval_id = f"eval-{uuid.uuid4().hex[:8]}"

        # 1. Shadow intent recognition (<1ms)
        intent = self._recognizer.evaluate(user_input)
        if intent is None or intent.level != DecisionIntentLevel.COMMITMENT:
            latency = (time.perf_counter() - start_time) * 1000.0
            report = PitfallEvaluationReport(
                evaluation_id=eval_id,
                intent_detected=intent is not None,
                intent_level=intent.level.value if intent else "none",
                triad_matched=False,
                alert_generated=False,
                dispatched_channel=DispatchChannel.SILENT.value,
                latency_ms=round(latency, 2),
            )
            return None, report

        # 2. Retrieve causal triad postmortems
        triads = await self._retriever.retrieve_matching_triads(intent)
        if not triads:
            latency = (time.perf_counter() - start_time) * 1000.0
            report = PitfallEvaluationReport(
                evaluation_id=eval_id,
                intent_detected=True,
                intent_level=intent.level.value,
                triad_matched=False,
                alert_generated=False,
                dispatched_channel=DispatchChannel.SILENT.value,
                latency_ms=round(latency, 2),
            )
            return None, report

        # Select highest severity triad
        triad = max(triads, key=lambda t: 2 if t.severity == AlertSeverity.CRITICAL else 1)
        drift_warning = self._retriever.evaluate_drift_warning(
            triad, current_runtime_version=current_runtime_version
        )

        # 3. Determine dispatch channel and session muting
        is_muted = self.is_subject_muted(session_id, triad.subject)
        if is_muted:
            channel = DispatchChannel.SILENT
        elif triad.severity == AlertSeverity.CRITICAL:
            channel = DispatchChannel.FRONTEND_CALLOUT
        else:
            channel = DispatchChannel.SHADOW_THOUGHT_ONLY

        alert_card = PitfallAlertCard(
            alert_id=f"alert-{uuid.uuid4().hex[:8]}",
            subject=triad.subject,
            intent_summary=f"计划选择方案: [{intent.proposed_solution}] (操作: {intent.action})",
            historical_pitfall=triad.pitfall_lesson,
            recommended_action=triad.validated_alternative,
            severity=triad.severity,
            source_ref=triad.incident_date or triad.source_id,
            drift_warning=drift_warning,
            dispatch_channel=channel,
            is_muted=is_muted,
        )

        latency = (time.perf_counter() - start_time) * 1000.0
        report = PitfallEvaluationReport(
            evaluation_id=eval_id,
            intent_detected=True,
            intent_level=intent.level.value,
            triad_matched=True,
            alert_generated=not is_muted,
            dispatched_channel=channel.value,
            latency_ms=round(latency, 2),
        )

        return (alert_card if not is_muted else None), report
