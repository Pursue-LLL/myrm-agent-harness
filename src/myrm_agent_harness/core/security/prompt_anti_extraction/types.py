"""Type definitions for System Prompt Anti-Extraction, JIT Sharding, and Canary Sentinel Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ShardCategory(StrEnum):
    """Categorization of system instruction shards."""

    CORE_BASE = "CORE_BASE"  # Always active baseline persona and constraints
    STAGE_RULE = "STAGE_RULE"  # Activated JIT when transitioning to specific task state
    PRIVATE_CONSTRAINT = "PRIVATE_CONSTRAINT"  # Highly confidential intellectual property constraint


@dataclass(slots=True, frozen=True)
class PromptShard:
    """An isolated modular instruction shard."""

    shard_id: str
    category: ShardCategory
    content: str
    applicable_stages: list[str] = field(default_factory=list)
    is_confidential: bool = False


@dataclass(slots=True, frozen=True)
class ExtractionDetectionResult:
    """Outcome of evaluating user input for system prompt extraction probes."""

    is_extraction_attempt: bool
    matched_pattern: str | None
    safe_fallback_response: str


@dataclass(slots=True, frozen=True)
class StreamingScanResult:
    """Real-time scan outcome for an outbound streaming chunk."""

    canary_detected: bool
    tripped: bool
    scrubbed_chunk: str
    alert_reason: str | None = None
