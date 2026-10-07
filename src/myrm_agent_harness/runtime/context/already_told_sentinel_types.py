"""Types and models for the already-told intent sentinel and instruction recall.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- RecallStatus: Status of the historical instruction recall attempt.
- HistoricalTurnInput: Represents a single historical turn for instruction recall lookup.
- ProvenanceCardPayload: Payload destined for UI provenance cards (WebUI / Desktop).
- InstructionRecallResult: Complete diagnostic and injection result produced by AlreadyToldIntentSentinel.

[POS]
Types and models for the already-told intent sentinel and instruction recall.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RecallStatus(StrEnum):
    """Status of the historical instruction recall attempt."""

    RECALLED_AND_ENFORCED = "RECALLED_AND_ENFORCED"
    FALLBACK_WARN = "FALLBACK_WARN"
    NOT_DETECTED = "NOT_DETECTED"


class HistoricalTurnInput(BaseModel):
    """Represents a single historical turn for instruction recall lookup."""

    model_config = ConfigDict(frozen=True)

    turn_index: int = Field(..., ge=0, description="Sequential turn index")
    role: str = Field(..., description="Role of the speaker (user, human, assistant)")
    content: str = Field(..., description="Message text content")
    timestamp_iso: str | None = Field(default=None, description="ISO timestamp if available")


class ProvenanceCardPayload(BaseModel):
    """Payload destined for UI provenance cards (WebUI / Desktop)."""

    model_config = ConfigDict(frozen=True)

    card_type: str = Field(default="historical_instruction_recall", description="UI card discriminator")
    detected: bool = Field(default=False, description="Whether intent was detected")
    trigger_pattern: str | None = Field(default=None, description="Regex/keyword trigger pattern matched")
    cue: str | None = Field(default=None, description="Subject cue extracted from user query")
    matched_turn_index: int | None = Field(default=None, description="Turn index of matched original instruction")
    matched_instruction: str | None = Field(default=None, description="Exact text of matched original instruction")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score")
    status: str = Field(default=RecallStatus.NOT_DETECTED.value, description="Recall outcome status")


class InstructionRecallResult(BaseModel):
    """Complete diagnostic and injection result produced by AlreadyToldIntentSentinel."""

    model_config = ConfigDict(frozen=True)

    detected: bool = Field(default=False, description="Whether 'already told' intent was detected")
    trigger_pattern: str | None = Field(default=None, description="Regex or pattern that triggered detection")
    extracted_cue: str | None = Field(default=None, description="Extracted keywords/cues from query")
    status: RecallStatus = Field(default=RecallStatus.NOT_DETECTED, description="Status of the recall")
    matched_turn_index: int | None = Field(default=None, description="Turn index of matched instruction")
    matched_instruction: str | None = Field(default=None, description="Exact instruction string recalled")
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score of recall")
    system_injection_block: str | None = Field(
        default=None, description="High-priority prompt injection block if recalled"
    )
    provenance_card: ProvenanceCardPayload = Field(..., description="UI provenance card payload")
