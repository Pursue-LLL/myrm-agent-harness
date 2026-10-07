"""Type contracts for Session-Dedup cross-turn content addressing and retrieve marker engine.

Defines schemas for three-level block chunking (System Prompt, Message Turns, Tool Payloads),
block-level fingerprint addressing, retrieve marker placeholders, and dedup savings telemetry.
Strictly adheres to 0 Any and typed dataclasses.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- BlockChunkLevel: Three-level logical boundary content chunking classification.
- SessionBlockFingerprint: Content-addressed fingerprint of a logical block in the conversation.
- SessionDedupConfig: Configuration governing cross-turn deduplication thresholds and chunking behavior.
- SessionDedupSavingsReport: Comprehensive telemetry report measuring token reduction across conversation
  turns.
- DedupedMessagePackage: Result of transforming a sequence of turn entries through the dedup processor.

[POS]
Type contracts for Session-Dedup cross-turn content addressing and retrieve marker engine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class BlockChunkLevel(StrEnum):
    """Three-level logical boundary content chunking classification."""

    SYSTEM_PROMPT = "system_prompt"  # Top-level prompt prefix, keeping byte-alignment
    MESSAGE_TURN = "message_turn"  # Individual User / Assistant dialog turn
    TOOL_PAYLOAD = "tool_payload"  # Heavy tool result or file read output


@dataclass(frozen=True, slots=True)
class SessionBlockFingerprint:
    """Content-addressed fingerprint of a logical block in the conversation."""

    chunk_hash: str
    level: BlockChunkLevel
    source_id: str
    byte_size: int
    token_estimate: int
    first_turn_seen: int
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(frozen=True, slots=True)
class SessionDedupConfig:
    """Configuration governing cross-turn deduplication thresholds and chunking behavior."""

    min_payload_chars: int = 150
    preview_chars: int = 100
    enable_tool_payload_dedup: bool = True
    enable_message_turn_dedup: bool = True
    marker_prefix: str = "[RetrieveMarker:"


@dataclass(frozen=True, slots=True)
class SessionDedupSavingsReport:
    """Comprehensive telemetry report measuring token reduction across conversation turns."""

    total_original_tokens: int
    total_deduped_tokens: int
    tokens_saved: int
    savings_ratio: float
    chunks_analyzed: int
    chunks_deduped: int
    markers_injected: int
    turn_index: int


@dataclass(frozen=True, slots=True)
class DedupedMessagePackage:
    """Result of transforming a sequence of turn entries through the dedup processor."""

    role: str
    content: str
    is_deduped: bool = False
    original_tokens: int = 0
    deduped_tokens: int = 0
    marker_id: str | None = None
