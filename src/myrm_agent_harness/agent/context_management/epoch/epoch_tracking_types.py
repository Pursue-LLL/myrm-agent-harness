"""Types and models for epoch tracking.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- EpochPhaseKind: Generational lifecycle phase for request epoch tracking.
- FirstDiffAreaKind: Categorization for prompt cache break root-cause attribution.
- ProjectionChangeKind: Dynamic context projection delta decision.
- OrderedToolSchema: Normalized and deterministically ordered tool specification.
- ProjectedContextDelta: Result of dynamic runtime context projection.
- EpochHeaderRecord: Immutable generational epoch header snapshot.
- CacheAttributionTelemetry: Telemetry diagnostic record for prompt cache observation.

[POS]
Types and models for epoch tracking.
"""

# ============================================================================
# Epoch Tracking & Request Compiler Data Contracts (Item 157)
# Pure typed contracts for DSH request compilation, generational EpochHeader,
# RuntimeContextProjection delta contracts, and PrefixDigest telemetry.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EpochPhaseKind(str, Enum):
    """Generational lifecycle phase for request epoch tracking."""

    INITIAL = "initial"  # First turn of a brand-new session
    RESUME = "resume"  # First turn after restoring from disk or external storage
    CHANGE = "change"  # Configuration, system prompt, or tool catalog mutated
    SERIES = "series"  # Steady continuation turn within the same series


class FirstDiffAreaKind(str, Enum):
    """Categorization for prompt cache break root-cause attribution."""

    NONE = "none"  # Complete cache hit, zero break detected
    SYSTEM_PROMPT = "system"  # System prompt mutated between turns
    TOOL_SCHEMA = "tools"  # Tool definitions, order, or schemas mutated
    MESSAGE_HISTORY = "messages"  # Prior conversation prefix modified retroactively
    PROVIDER_EVICTION = "provider_eviction"  # Digest identical but provider missed (LRU/cold restart)
    PARAM_MISMATCH = "param_mismatch"  # Model or inference parameter changed


class ProjectionChangeKind(str, Enum):
    """Dynamic context projection delta decision."""

    NOOP = "noop"  # Content unchanged from last projection, zero token append
    DELTA_APPEND = "delta_append"  # State mutated, append delta at turn tail
    INVALIDATION_CLEAR = "invalidation_clear"  # Policy cleared, append explicit invalidate marker


@dataclass(frozen=True, slots=True)
class OrderedToolSchema:
    """Normalized and deterministically ordered tool specification."""

    name: str
    description: str
    parameters_schema_json: str
    schema_digest: str


@dataclass(frozen=True, slots=True)
class ProjectedContextDelta:
    """Result of dynamic runtime context projection."""

    kind: ProjectionChangeKind
    namespace: str
    delta_content: str | None
    snapshot_hash: str


@dataclass(frozen=True, slots=True)
class EpochHeaderRecord:
    """Immutable generational epoch header snapshot."""

    epoch_id: str
    session_id: str
    generation: int
    phase: EpochPhaseKind
    starts_series: bool
    provider: str
    model: str
    temperature: float
    system_prompt_digest: str
    tools_schema_digest: str
    prefix_digest: str
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class CacheAttributionTelemetry:
    """Telemetry diagnostic record for prompt cache observation."""

    session_id: str
    generation: int
    prefix_digest: str
    cache_read_tokens: int
    cache_miss_tokens: int
    first_diff_area: FirstDiffAreaKind
    is_runtime_defect: bool
    diagnostic_hint: str
