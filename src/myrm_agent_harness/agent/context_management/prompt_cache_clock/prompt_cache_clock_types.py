"""Strongly typed contracts for Tiered Prompt Cache and Hour Clock Governor Suite (Item 222).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- ClockBucketResolution: Time granularity used to stabilize dynamic clock strings.
- ToolChoiceMode: Classification of tool calling dispatch mode (auto vs. forced).
- CacheTierKind: Layering classification of prompt segments (Tier 1 static, Tier 2 context, Tier 3 transient).
- ContextClockSpec: Normalized coarse-grained timestamp descriptor preventing cache bust.
- PromptCacheTierBlock: Individual content block labeled with tier kind and cache breakpoint status.
- TieredAssemblyResult: Composed request layout ready for LLM invocation with stabilized cache prefixes.
- PromptCacheClockConfig: Tunable configuration parameters for clock bucketing and cache bypass.

[POS]
- Eliminates prompt cache invalidation caused by second-by-second clock ticking and forced tool choice,
- achieving 90%+ prompt cache hit ratios inspired by Anthropic Commerce Agents.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class ClockBucketResolution(str, enum.Enum):
    """Resolution for quantizing the dynamic session clock to preserve byte stability."""

    HOUR_BUCKET = "hour_bucket"
    HALF_HOUR_BUCKET = "half_hour_bucket"
    DAY_BUCKET = "day_bucket"


class ToolChoiceMode(str, enum.Enum):
    """Classification of tool choice configuration."""

    AUTO = "auto"
    FORCED_TOOL = "forced_tool"
    NONE = "none"
    REQUIRED = "required"


class CacheTierKind(str, enum.Enum):
    """Architectural layer of the assembled LLM request prompt."""

    TIER_1_STATIC_GLOBAL = "tier_1_static_global"
    TIER_2_SESSION_CONTEXT = "tier_2_session_context"
    TIER_3_TRANSIENT_TURN = "tier_3_transient_turn"


@dataclass(frozen=True, slots=True)
class ContextClockSpec:
    """Coarse-grained bucketed timestamp providing date/time perception without cache thrashing."""

    timestamp: float
    bucketed_time_str: str
    bucket_resolution: ClockBucketResolution
    time_zone_offset_hours: float

    def to_dict(self) -> dict[str, object]:
        """Serializes clock spec to dictionary."""
        return {
            "timestamp": self.timestamp,
            "bucketed_time_str": self.bucketed_time_str,
            "bucket_resolution": self.bucket_resolution.value,
            "time_zone_offset_hours": self.time_zone_offset_hours,
        }


@dataclass(frozen=True, slots=True)
class PromptCacheTierBlock:
    """Structured prompt segment categorized into a cache stability tier."""

    tier: CacheTierKind
    content: str
    has_cache_breakpoint: bool
    byte_length: int

    def to_dict(self) -> dict[str, object]:
        """Serializes cache tier block to dictionary."""
        return {
            "tier": self.tier.value,
            "content": self.content,
            "has_cache_breakpoint": self.has_cache_breakpoint,
            "byte_length": self.byte_length,
        }


@dataclass(frozen=True, slots=True)
class TieredAssemblyResult:
    """Composed system blocks and cache breakpoint metadata ready for inference."""

    system_blocks: list[dict[str, object]]
    total_prefix_bytes: int
    cache_breakpoints_count: int
    rolling_breakpoint_eligible: bool
    context_clock_str: str

    def to_dict(self) -> dict[str, object]:
        """Serializes tiered assembly outcome."""
        return {
            "system_blocks": list(self.system_blocks),
            "total_prefix_bytes": self.total_prefix_bytes,
            "cache_breakpoints_count": self.cache_breakpoints_count,
            "rolling_breakpoint_eligible": self.rolling_breakpoint_eligible,
            "context_clock_str": self.context_clock_str,
        }


@dataclass(frozen=True, slots=True)
class PromptCacheClockConfig:
    """Tunable configuration governing clock bucketing and prompt cache assembly."""

    clock_resolution: ClockBucketResolution = ClockBucketResolution.HOUR_BUCKET
    bypass_cache_on_forced_tool: bool = True
    enable_three_tier_layout: bool = True
    default_timezone_offset_hours: float = 0.0
    include_cache_control_header: bool = True
