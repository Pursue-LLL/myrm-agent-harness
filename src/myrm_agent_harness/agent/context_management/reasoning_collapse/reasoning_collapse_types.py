"""Types and schemas for deep reasoning stream thinking collapse and prompt cache alignment.

Defines multi-vendor reasoning blocks, sliding window collapse modes,
prompt cache alignment checks, and compression reports.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ReasoningVendorType: Vendor-specific reasoning output format.
- ThinkingCollapseMode: Strategy for collapsing historical reasoning chains.
- UnifiedReasoningBlock: Normalized internal representation of a reasoning thought trace.
- ReasoningCollapseReport: Metrics report detailing token reduction and cache alignment integrity.
- ReasoningCollapseConfig: Configuration governing sliding window size and digest thresholds.

[POS]
Types and schemas for deep reasoning stream thinking collapse and prompt cache alignment.
"""

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time


class ReasoningVendorType(str, Enum):
    """Vendor-specific reasoning output format."""

    DEEPSEEK = "deepseek_r1"  # reasoning_content
    OPENAI_O1 = "openai_o1_o3"  # thought_tokens / reasoning_tokens
    ANTHROPIC_CLAUDE = "anthropic_claude"  # thinking block
    GENERIC = "generic_reasoning"


class ThinkingCollapseMode(str, Enum):
    """Strategy for collapsing historical reasoning chains."""

    FULL_RETAIN = "full_retain"
    SLIDING_WINDOW = "sliding_window"
    DIGEST_ONLY = "digest_only"
    AGGRESSIVE_PRUNE = "aggressive_prune"


@dataclass
class UnifiedReasoningBlock:
    """Normalized internal representation of a reasoning thought trace."""

    turn_index: int
    vendor: ReasoningVendorType
    raw_content: str
    token_estimate: int
    signature: str
    is_collapsed: bool = False
    digest_summary: str = ""
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        turn_index: int,
        vendor: ReasoningVendorType,
        raw_content: str,
        token_estimate: int,
    ) -> "UnifiedReasoningBlock":
        """Construct block with SHA256 signature for cache traceability."""
        digest = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        return cls(
            turn_index=turn_index,
            vendor=vendor,
            raw_content=raw_content,
            token_estimate=token_estimate,
            signature=digest[:16],
        )


@dataclass
class ReasoningCollapseReport:
    """Metrics report detailing token reduction and cache alignment integrity."""

    session_id: str
    total_turns: int
    active_turn_index: int
    original_reasoning_tokens: int
    collapsed_reasoning_tokens: int
    tokens_saved: int
    compression_ratio: float
    cache_prefix_aligned: bool
    generated_at: float = field(default_factory=time.time)


@dataclass
class ReasoningCollapseConfig:
    """Configuration governing sliding window size and digest thresholds."""

    mode: ThinkingCollapseMode = ThinkingCollapseMode.SLIDING_WINDOW
    sliding_window_turns: int = 1  # Number of recent turns to keep uncollapsed
    max_digest_tokens: int = 80
    preserve_system_prefix: bool = True
    min_tokens_to_collapse: int = 120
