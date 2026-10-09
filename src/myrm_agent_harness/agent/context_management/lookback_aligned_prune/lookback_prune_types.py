"""Contracts and data models for prompt cache lookback position aligned pruning floor.

[INPUT]
- None (pure domain types and enum contracts).

[OUTPUT]
- Exports data contracts for provider cache profiles, projected content blocks,
  lookback floor results, prune decisions, and configuration models.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.lookback_aligned_prune
- Module: lookback_prune_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Sequence


class ProviderCacheKind(str, Enum):
    """Categorization of model providers with distinct prompt cache lookback limits."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE_GEMINI = "google_gemini"
    GENERIC = "generic"


class ContentBlockKind(str, Enum):
    """Types of discrete content blocks emitted to provider LLM endpoints."""

    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    IMAGE = "image"
    FILE_REFERENCE = "file_reference"


@dataclass(frozen=True)
class ProjectedContentBlock:
    """A discrete emitted block within a message turn counted towards cache lookback positions."""

    message_index: int
    block_kind: ContentBlockKind
    token_count: int
    identifier: Optional[str] = None
    is_prunable_tool_output: bool = False


@dataclass(frozen=True)
class LookbackFloorResult:
    """Outcome of computing the protected lookback boundary."""

    total_projected_blocks: int
    lookback_window_positions: int
    reserved_headroom_positions: int
    protected_floor_message_index: int
    protected_floor_block_index: int
    diagnostic_reason: str


@dataclass(frozen=True)
class LookbackPruneDecision:
    """Decision specifying whether a tool result can be safely pruned without cache rupture."""

    message_index: int
    can_prune: bool
    is_protected_by_floor: bool
    estimated_saved_tokens: int
    reason: str


@dataclass(frozen=True)
class LookbackAlignedPruneConfig:
    """Configuration governing lookback positions, headroom reservation, and safety boundaries."""

    default_lookback_positions: int = 20
    reserved_headroom_positions: int = 6
    provider_lookback_overrides: Mapping[str, int] = field(
        default_factory=lambda: {
            "anthropic": 20,
            "openai": 32,
            "google_gemini": 16,
            "generic": 16,
        }
    )
    max_token_budget_for_suffix: int = 12000
