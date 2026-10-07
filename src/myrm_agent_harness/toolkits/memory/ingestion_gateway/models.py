"""[POS]: src/myrm_agent_harness/toolkits/memory/ingestion_gateway/models.py
[INPUT]: Core domain primitives and status enumerations for universal context ingestion gateway.
[OUTPUT]: Strongly typed IngestionSourceType, VoiceTranscriptSegment, ContextIngestionPayload, and IngestionDigestResult contracts.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class IngestionSourceType(StrEnum):
    """Source protocol type for context ingestion."""

    PLAUD_VOICE_CARD = "plaud_voice_card"
    WEBVTT = "webvtt"
    SRT = "srt"
    RAW_TRANSCRIPT = "raw_transcript"
    WEBHOOK = "webhook"


class VoiceTranscriptSegment(BaseModel):
    """Normalized audio transcript segment with speaker identification and timestamps."""

    speaker: str = Field(default="Speaker", description="Identified speaker label or name")
    start_sec: float = Field(default=0.0, ge=0.0, description="Start timestamp in seconds")
    end_sec: float = Field(default=0.0, ge=0.0, description="End timestamp in seconds")
    text: str = Field(..., description="Spoken transcript text snippet")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="ASR recognition confidence")


class ContextIngestionPayload(BaseModel):
    """Universal payload container received by the context ingestion gateway."""

    source_type: IngestionSourceType = Field(..., description="Format or source device protocol")
    device_id: str = Field(default="unknown_device", description="Identifier of the recording hardware")
    title: str = Field(default="Untitled Audio Recording", description="Title or meeting topic")
    raw_payload: str = Field(..., description="Raw text, JSON, WebVTT, or SRT string")
    session_id: str | None = Field(default=None, description="Optional target session ID to attach")
    metadata: dict[str, str] = Field(default_factory=dict, description="Custom contextual metadata tags")


class IngestionDigestResult(BaseModel):
    """Outcome report of context ingestion, distillation, and deduplication."""

    fingerprint: str = Field(..., description="SHA-256 content deduplication hash")
    title: str = Field(..., description="Meeting or voice recording title")
    source_type: str = Field(..., description="Original source protocol type")
    speaker_count: int = Field(default=0, ge=0, description="Number of distinct speakers detected")
    segment_count: int = Field(default=0, ge=0, description="Total normalized segments parsed")
    summary: str = Field(default="", description="Distilled high-level overview")
    action_items: list[str] = Field(default_factory=list, description="Extracted action items and tasks")
    decisions: list[str] = Field(default_factory=list, description="Extracted agreements or decisions")
    is_duplicate: bool = Field(default=False, description="Flag indicating if recording was already ingested")
    created_at_epoch: float = Field(..., description="Epoch timestamp of ingestion processing")
