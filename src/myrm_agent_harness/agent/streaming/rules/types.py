"""Type definitions and contracts for Time-Traveling Stream Rules (TTSR).

Provides strongly typed rule descriptors, action declarations, and match result models.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

RuleTarget = Literal["assistant", "thinking", "tool_args", "all"]
RuleAction = Literal["abort_and_retry", "warn_only"]


@dataclass(frozen=True)
class StreamRule:
    """Strongly typed dormant stream rule descriptor for TTSR engine.

    Rules evaluate against real-time streaming chunks without entering the system prompt.
    """

    rule_id: str
    name: str
    pattern: re.Pattern[str]
    target: RuleTarget = "all"
    reminder: str = ""
    repeat_gap: int = 10
    action: RuleAction = "abort_and_retry"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TtsrMatchResult:
    """Encapsulates a verified match of a stream rule against active token flow."""

    rule: StreamRule
    matched_text: str
    target: RuleTarget
    turn: int
