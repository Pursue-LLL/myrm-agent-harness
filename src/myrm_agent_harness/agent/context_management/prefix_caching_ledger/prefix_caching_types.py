"""Domain models and contracts for prefix caching aligned layout and hidden reasoning token ledger.

[INPUT]
- None (Self-contained domain models and contracts).

[OUTPUT]
- ContextTier: Three-tier classification (TIER1_STATIC_PREFIX, TIER2_SEMI_STATIC_PROJECT, TIER3_DYNAMIC_TAIL).
- ContextBlockDescriptor: Structured descriptor of a context segment with tier, content, and token counts.
- TokenUsageBreakdown: Multi-dimensional breakdown covering input, output, reasoning, cache read/write.
- TurnLedgerRecord: Audited record of token usage for a single turn in a session.
- PrefixCachingLayoutConfig: Configuration governing ordering rules, sorting, and pricing parameters.

[POS]
Domain contract layer for prompt prefix caching optimization and full-spectrum token ledger accounting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class ContextTier(str, Enum):
    """Hierarchical tier classifying context blocks by mutation frequency and cache affinity."""

    TIER1_STATIC_PREFIX = "tier1_static_prefix"
    TIER2_SEMI_STATIC_PROJECT = "tier2_semi_static_project"
    TIER3_DYNAMIC_TAIL = "tier3_dynamic_tail"


@dataclass(frozen=True)
class ContextBlockDescriptor:
    """Atomic block of context designated to a specific caching tier."""

    block_id: str
    tier: ContextTier
    category: str
    content: str
    sort_key: str = ""
    estimated_tokens: int = 0


@dataclass(frozen=True)
class TokenUsageBreakdown:
    """Audited multi-dimensional token usage breakdown across all provider channels."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Sum of visible/raw input and output tokens."""
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of input tokens resolved via provider KV cache."""
        if self.input_tokens <= 0:
            return 0.0
        return min(1.0, max(0.0, self.cache_read_tokens / self.input_tokens))

    @property
    def reasoning_ratio(self) -> float:
        """Fraction of output tokens consumed by internal reasoning/thinking steps."""
        if self.output_tokens <= 0:
            return 0.0
        return min(1.0, max(0.0, self.reasoning_tokens / self.output_tokens))


@dataclass(frozen=True)
class TurnLedgerRecord:
    """Immutable audit record for a single conversation turn in the ledger."""

    turn_id: str
    model_name: str
    timestamp: float
    usage: TokenUsageBreakdown
    prefix_cache_hit: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PrefixCachingLayoutConfig:
    """Configuration governing prefix caching layout alignment and token accounting."""

    enforce_tier_strict_ordering: bool = True
    sort_tools_alphabetically: bool = True
    clock_stamp_tier: ContextTier = ContextTier.TIER3_DYNAMIC_TAIL
    default_cache_discount_rate: float = 0.9
    prefix_stability_hash_algorithm: str = "sha256"
