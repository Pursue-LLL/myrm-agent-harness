"""Anti-amnesia compression fallback guard and window aligned resilience package.

[INPUT]
- anti_amnesia_types::* (POS: Type definitions)
- window_capacity_asserter::WindowCapacityAsserter, InsufficientWindowCapacityError (POS: Capacity asserters)
- chunked_map_reduce_compactor::ChunkedMapReduceCompactor (POS: Map-reduce compactor)
- compression_guard_and_watchdog::CompressionTransparencyAndLockGuard, AdaptiveTurnBudgetWatchdog, CompressionLockTimeoutError (POS: Guard and watchdogs)
- anti_amnesia_suite::AntiAmnesiaSuite, ContextCompressionSilentFallbackGuardAndWindowAlignedAntiAmnesiaSuite (POS: Suite facades)

[OUTPUT]
- Public exports of anti-amnesia types, engines, and unified suites.

[POS]
Exports for context compression fallback protection against silent truncation,
hierarchical map-reduce compression, transparency HUD, and 500-turn watchdog.
"""

from __future__ import annotations

from .anti_amnesia_suite import (
    AntiAmnesiaSuite,
    ContextCompressionSilentFallbackGuardAndWindowAlignedAntiAmnesiaSuite,
)
from .anti_amnesia_types import (
    AntiAmnesiaExecutionReport,
    CapacityAssertionResult,
    ChunkedSummaryNode,
    CompressionFallbackTier,
    CompressionTransparencyHudState,
    ModelWindowSpec,
    TurnBudgetWatchdogState,
)
from .chunked_map_reduce_compactor import ChunkedMapReduceCompactor
from .compression_guard_and_watchdog import (
    AdaptiveTurnBudgetWatchdog,
    CompressionLockTimeoutError,
    CompressionTransparencyAndLockGuard,
)
from .window_capacity_asserter import (
    InsufficientWindowCapacityError,
    WindowCapacityAsserter,
)

__all__ = [
    "AdaptiveTurnBudgetWatchdog",
    "AntiAmnesiaExecutionReport",
    "AntiAmnesiaSuite",
    "CapacityAssertionResult",
    "ChunkedMapReduceCompactor",
    "ChunkedSummaryNode",
    "CompressionFallbackTier",
    "CompressionLockTimeoutError",
    "CompressionTransparencyAndLockGuard",
    "CompressionTransparencyHudState",
    "ContextCompressionSilentFallbackGuardAndWindowAlignedAntiAmnesiaSuite",
    "InsufficientWindowCapacityError",
    "ModelWindowSpec",
    "TurnBudgetWatchdogState",
    "WindowCapacityAsserter",
]
