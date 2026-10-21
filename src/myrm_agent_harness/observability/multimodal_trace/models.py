"""[INPUT] Multimodal media objects (screenshots, attachments, audio, video) and trace events.
[OUTPUT] Immutable media references, OTel GenAI compliant multimodal parts, and 3-step inspector models.
[POS] myrm_agent_harness.observability.multimodal_trace.models

Decouples heavy binary media objects from trace spans:
1. MediaReference: URI, SHA256, MIME, and size metadata with 4-state visibility lifecycle.
2. MultimodalMessagePart: Strict alignment with OTel GenAI semantic conventions.
3. MultimodalTraceRecord: Input-Execution-Feedback 3-step inspection trace with Golden Eval pinning.
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class MediaModality(str, Enum):
    """Supported multimedia modalities."""

    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


class MediaVisibilityState(str, Enum):
    """4-state visibility lifecycle preventing false-positive broken image assumptions."""

    READY = "ready"           # File is active and previewable
    UPLOADING = "uploading"   # Asynchronous upload in progress
    EXPIRED = "expired"       # Presigned preview token has expired
    PURGED = "purged"         # Binary cleaned by TTL policy; hash and metadata preserved


class MultimodalStepType(str, Enum):
    """Standardized 3-step diagnostic pipeline for multimodal agents."""

    INPUT = "input"           # Step 1: Visual / attachment input context
    EXECUTION = "execution"   # Step 2: Tool execution, browser clicks, code patches
    FEEDBACK = "feedback"     # Step 3: Result verification or user response


@dataclass(frozen=True)
class MediaReference:
    """Lightweight metadata pointer replacing bulky Base64 payloads inside traces."""

    media_id: str
    uri: str
    modality: MediaModality
    mime_type: str
    file_size_bytes: int
    sha256_hash: str
    visibility_state: MediaVisibilityState = MediaVisibilityState.READY
    presigned_preview_url: str = ""
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | int]:
        return {
            "media_id": self.media_id,
            "uri": self.uri,
            "modality": self.modality.value,
            "mime_type": self.mime_type,
            "file_size_bytes": self.file_size_bytes,
            "sha256_hash": self.sha256_hash,
            "visibility_state": self.visibility_state.value,
            "presigned_preview_url": self.presigned_preview_url,
            "created_at_ms": self.created_at_ms,
        }


@dataclass(frozen=True)
class MultimodalMessagePart:
    """OTel GenAI compliant message part representation."""

    part_type: str  # "text" or "media_reference"
    content: str = ""
    media_ref: MediaReference | None = None

    def to_dict(self) -> dict[str, str | dict[str, str | int] | None]:
        return {
            "part_type": self.part_type,
            "content": self.content,
            "media_ref": self.media_ref.to_dict() if self.media_ref else None,
        }


@dataclass(frozen=True)
class MultimodalTraceStep:
    """Step in the Input-Execution-Feedback 3-step diagnostic inspector."""

    step_index: int
    step_type: MultimodalStepType
    description: str
    media_ids: tuple[str, ...] = ()
    status: str = "success"
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, int | str | list[str]]:
        return {
            "step_index": self.step_index,
            "step_type": self.step_type.value,
            "description": self.description,
            "media_ids": list(self.media_ids),
            "status": self.status,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(frozen=True)
class MultimodalTraceRecord:
    """Full-lifecycle trace record for multimodal runs."""

    trace_id: str
    session_id: str
    prompt_summary: str
    media_references: tuple[MediaReference, ...]
    steps: tuple[MultimodalTraceStep, ...]
    pinned_for_golden_eval: bool = False
    golden_eval_category: str = ""
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | int | bool | list[dict[str, str | int]] | list[dict[str, int | str | list[str]]]]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "prompt_summary": self.prompt_summary,
            "media_references": [m.to_dict() for m in self.media_references],
            "steps": [s.to_dict() for s in self.steps],
            "pinned_for_golden_eval": self.pinned_for_golden_eval,
            "golden_eval_category": self.golden_eval_category,
            "created_at_ms": self.created_at_ms,
        }
