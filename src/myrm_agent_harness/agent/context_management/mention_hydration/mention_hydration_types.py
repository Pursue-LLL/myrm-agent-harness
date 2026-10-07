"""Types and data contracts for GUI-first @-mention zero-turn context hydration.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- MentionKind: Classification of an @-mention entity in user prompts.
- PreHydratedAttachment: Fully or partially hydrated workspace entity attached to a message.
- MentionHydrationConfig: Safeguards for payload sizes, deduplication, and truncation.
- HydratedTurnPayload: Enriched user prompt payload ready for single-turn zero-tool LLM decoding.

[POS]
Data contracts for zero-turn @-mention extraction, deduplication, and context injection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MentionKind(str, Enum):
    """Classification of an @-mention entity in user prompts."""

    FILE = "file"
    ARTIFACT = "artifact"
    WIKI = "wiki"
    SNIPPET = "snippet"


@dataclass(frozen=True, slots=True)
class PreHydratedAttachment:
    """Fully or partially hydrated workspace entity attached to a message.

    Transfers file content into the prompt context prior to the first model turn,
    eliminating redundant read_file round-trips.
    """

    path: str
    kind: MentionKind
    content: str
    content_hash: str
    byte_size: int
    is_truncated: bool = False
    mime_type: str = "text/plain"


@dataclass(frozen=True, slots=True)
class MentionHydrationConfig:
    """Safeguards for payload sizes, deduplication, and truncation."""

    max_file_bytes: int = 30720  # Max 30KB per file before truncation
    max_total_attachments_bytes: int = 102400  # Max 100KB across all attachments in turn
    enable_hash_dedup: bool = True  # Avoid re-injecting full content if hash seen in session
    head_preserve_bytes: int = 15360  # Preserved head on overflow
    tail_preserve_bytes: int = 10240  # Preserved tail on overflow


@dataclass(frozen=True, slots=True)
class HydratedTurnPayload:
    """Enriched user prompt payload ready for single-turn zero-tool LLM decoding.

    Pairs the original prompt with pre-hydrated attachments rendered in standard XML blocks,
    calculating estimated round-trips and output token savings.
    """

    session_id: str
    original_prompt: str
    hydrated_prompt: str
    attachments: tuple[PreHydratedAttachment, ...]
    deduped_attachments_count: int
    estimated_roundtrips_saved: int
    estimated_tokens_saved: int
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
