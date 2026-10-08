"""Data models for proactive past-pitfall alert and decision assist.

[POS]
Defines strongly-typed contracts for shadow decision intent classification,
causal triad postmortems, non-intrusive alert callouts, and evaluation reports.

[INPUT]
- enum.StrEnum, pydantic.BaseModel, pydantic.Field

[OUTPUT]
- DecisionIntentLevel, AlertSeverity, DispatchChannel
- DecisionIntent, PitfallTriadRecord, PitfallAlertCard, PitfallEvaluationReport
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DecisionIntentLevel(StrEnum):
    """Classification of user decision commitment."""

    INQUIRY = "inquiry"  # Exploratory discussion or hypothetical question
    COMMITMENT = "commitment"  # Substantial engineering or architectural choice


class AlertSeverity(StrEnum):
    """Urgency level of a proactive alert."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class DispatchChannel(StrEnum):
    """Destination channel for proactive alerts."""

    FRONTEND_CALLOUT = "frontend_callout"  # Prominent non-intrusive UI banner
    SHADOW_THOUGHT_ONLY = "shadow_thought_only"  # Injected into model reflection without UI pop
    SILENT = "silent"  # Suppressed due to mute or low confidence


class DecisionIntent(BaseModel):
    """Extracted intention representing an architectural or technical choice."""

    intent_id: str = Field(description="Unique intent evaluation identifier")
    level: DecisionIntentLevel = Field(description="Commitment level: inquiry or commitment")
    action: str = Field(description="Key verb or mutation (e.g. replace, refactor, disable)")
    target_subject: str = Field(description="Target technical subject or component (e.g. Redis, distributed lock)")
    proposed_solution: str = Field(description="Proposed alternative or candidate library")
    confidence: float = Field(ge=0.0, le=1.0, description="Detection confidence score")
    raw_query: str = Field(description="Original user statement or code context")


class PitfallTriadRecord(BaseModel):
    """Historical postmortem structured as a causal triad: approach, pitfall, alternative."""

    triad_id: str = Field(description="Unique record identifier")
    subject: str = Field(description="Technical subject or component keyword")
    approach: str = Field(description="Approach previously attempted")
    pitfall_lesson: str = Field(description="Failure symptom, bottleneck, or postmortem root cause")
    validated_alternative: str = Field(description="Alternative successfully deployed to avoid the pitfall")
    severity: AlertSeverity = Field(default=AlertSeverity.WARNING, description="Severity grade")
    version_context: str = Field(default="", description="Dependency version context when failure occurred")
    incident_date: str = Field(default="", description="Historical date or project reference")
    negative_markers: list[str] = Field(default_factory=list, description="Associated negative sentiment tags")
    source_id: str = Field(description="Origin episodic memory or decision lineage reference")


class PitfallAlertCard(BaseModel):
    """Structured callout card rendered non-intrusively in UI or injected into shadow prompt."""

    alert_id: str = Field(description="Unique alert identifier")
    subject: str = Field(description="Technical subject trigger")
    intent_summary: str = Field(description="Human-readable summary of user's proposed choice")
    historical_pitfall: str = Field(description="Historical failure lesson and root cause")
    recommended_action: str = Field(description="Validated battle-tested alternative advice")
    severity: AlertSeverity = Field(description="Severity grade")
    source_ref: str = Field(description="Historical project or date anchor")
    drift_warning: str = Field(default="", description="Notice if historical environment has since evolved")
    dispatch_channel: DispatchChannel = Field(
        default=DispatchChannel.FRONTEND_CALLOUT, description="Dispatch channel"
    )
    is_muted: bool = Field(default=False, description="Whether alert is muted in current session")


class PitfallEvaluationReport(BaseModel):
    """Audit report detailing proactive decision evaluation results."""

    evaluation_id: str = Field(description="Unique evaluation identifier")
    intent_detected: bool = Field(description="Whether a decision intent was identified")
    intent_level: str = Field(default="none", description="Intent commitment level")
    triad_matched: bool = Field(description="Whether a causal historical pitfall was matched")
    alert_generated: bool = Field(description="Whether an alert card was dispatched")
    dispatched_channel: str = Field(default="none", description="Dispatch channel used")
    latency_ms: float = Field(ge=0.0, description="Wall-clock evaluation duration in milliseconds")
