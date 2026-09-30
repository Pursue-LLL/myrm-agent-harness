"""Loop scheduling runtime package.

Exports pure parsing, semantic fingerprinting, adaptive backoff, and DTOs.
"""

from __future__ import annotations

from .backoff import AdaptiveBackoffCalculator, BackoffDecision
from .fingerprint import extract_semantic_fingerprint, has_alert_anomaly
from .parser import (
    build_wakeup_prompt,
    format_interval,
    is_loop_complete_response,
    parse_interval_token,
    parse_loop_args,
)
from .types import (
    DEFAULT_MAX_TICKS,
    DEFAULT_MIN_INTERVAL_SECONDS,
    DEFAULT_SELF_PACED_CEILING_SECONDS,
    DEFAULT_SELF_PACED_FLOOR_SECONDS,
    LOOP_COMPLETE_MARKER,
    LoopConfig,
    LoopMode,
    LoopState,
    LoopStatus,
    LoopStopReason,
)

__all__ = [
    "AdaptiveBackoffCalculator",
    "BackoffDecision",
    "DEFAULT_MAX_TICKS",
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "DEFAULT_SELF_PACED_CEILING_SECONDS",
    "DEFAULT_SELF_PACED_FLOOR_SECONDS",
    "LOOP_COMPLETE_MARKER",
    "LoopConfig",
    "LoopMode",
    "LoopState",
    "LoopStatus",
    "LoopStopReason",
    "build_wakeup_prompt",
    "extract_semantic_fingerprint",
    "format_interval",
    "has_alert_anomaly",
    "is_loop_complete_response",
    "parse_interval_token",
    "parse_loop_args",
]
