"""Types and data models for deterministic hash-pinned prefix cache guard and append-only pipeline.

Defines cache partition zones, SHA-256 prefix fingerprints, cache hit telemetry,
and deterministic summarization blocks.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- PrefixCacheZoneKind: Partition zone within the model's physical prefix-cached prompt sequence.
- PrefixHashFingerprint: SHA-256 anchored cryptographic fingerprint for prompt prefix stability.
- PrefixCacheHitReport: Telemetry report recording model-reported KV-cache hit statistics and breach
  diagnostics.
- DeterministicSummaryBlock: Immutable, deterministic summary block with pinned seed and cryptographic hash.

[POS]
Types and data models for deterministic hash-pinned prefix cache guard and append-only pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PrefixCacheZoneKind(StrEnum):
    """Partition zone within the model's physical prefix-cached prompt sequence."""

    STATIC_SYSTEM_FROZEN = "static_system_frozen"
    APPEND_ONLY_IMMUTABLE_HISTORY = "append_only_immutable_history"
    ACTIVE_WORKING_TAIL = "active_working_tail"


@dataclass(frozen=True)
class PrefixHashFingerprint:
    """SHA-256 anchored cryptographic fingerprint for prompt prefix stability."""

    session_id: str
    turn_index: int
    static_system_sha256: str
    immutable_history_sha256: str
    combined_prefix_sha256: str
    prefix_length_chars: int
    timestamp: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PrefixCacheHitReport:
    """Telemetry report recording model-reported KV-cache hit statistics and breach diagnostics."""

    session_id: str
    turn_index: int
    is_prefix_stable: bool
    reported_cache_hit_tokens: int
    reported_total_prompt_tokens: int
    cache_hit_ratio: float
    breach_detected: bool
    breach_reason: str | None = None
    timestamp: float = 0.0


@dataclass(frozen=True)
class DeterministicSummaryBlock:
    """Immutable, deterministic summary block with pinned seed and cryptographic hash."""

    summary_id: str
    deterministic_seed: int
    source_turns_range: tuple[int, int]
    content: str
    sha256_hash: str
    created_at: float
