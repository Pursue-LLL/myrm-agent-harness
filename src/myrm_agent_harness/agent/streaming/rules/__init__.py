"""Time-Traveling Stream Rules (TTSR) zero-tax streaming rule engine.

Provides zero-token-tax dormant rule evaluation, sliding-window chunk regex matching,
immediate mid-token stream interruption, bounded retry breaker, and compaction-immune injection.
"""

from __future__ import annotations

from myrm_agent_harness.agent.streaming.rules.coordinator import TtsrCoordinator
from myrm_agent_harness.agent.streaming.rules.matcher import (
    PartialJsonUnescaper,
    TtsrMatcher,
)
from myrm_agent_harness.agent.streaming.rules.types import (
    RuleAction,
    RuleTarget,
    StreamRule,
    TtsrMatchResult,
)

__all__ = [
    "PartialJsonUnescaper",
    "RuleAction",
    "RuleTarget",
    "StreamRule",
    "TtsrCoordinator",
    "TtsrMatchResult",
    "TtsrMatcher",
]
