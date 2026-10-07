"""Type definitions for screen and desktop observation memory safety gate.

[INPUT]
- typing: Literal, Optional, List, Dict
- dataclasses: dataclass, field
- datetime: datetime, timezone

[OUTPUT]
- ObservationSourceType, ObservationPayload, SanitizedObservationEvidence
- DescriptiveFactCandidate, OverpromotionGateResult, ScreenSafetyAuditRecord

[POS]
Harness framework layer contracts for ChatGPT Desktop Skysight-style
anti-injection evidence boundary and descriptive-only fact validation (Topic 01 Item 85).
Strict typing applied: No `any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

ObservationSourceType = Literal[
    "ax_tree",
    "ocr_text",
    "screenshot_summary",
    "browser_dom",
    "terminal_output",
]

PromotionStatus = Literal[
    "transient_observation",
    "candidate_pattern",
    "promoted_preference",
    "rejected_injection",
]


@dataclass(frozen=True)
class ObservationPayload:
    """Raw observation payload captured from host desktop or screen."""

    source_type: ObservationSourceType
    raw_text: str
    app_name: str = "UnknownApp"
    window_title: str = "Untitled"
    session_id: str = "default_session"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    app_bundle_id: str = ""


@dataclass(frozen=True)
class SanitizedObservationEvidence:
    """Observation evidence safely wrapped with immutable security boundaries."""

    is_safe: bool
    risk_score: float
    detected_injection_patterns: list[str]
    isolated_prompt_segment: str
    redacted_text: str
    original_char_count: int


@dataclass(frozen=True)
class DescriptiveFactCandidate:
    """An extracted factual statement evaluated for descriptive grammar compliance."""

    statement: str
    is_descriptive: bool
    imperative_detected: bool
    violation_reasons: list[str]
    rewritten_statement: str


@dataclass(frozen=True)
class OverpromotionGateResult:
    """Evaluation result determining whether an observed fact can be promoted to a stable preference."""

    status: PromotionStatus
    frequency_count: int
    distinct_sessions_count: int
    is_promoted: bool
    explanation: str
    pattern_fingerprint: str


@dataclass(frozen=True)
class ScreenSafetyAuditRecord:
    """Audit ledger record capturing boundary, syntax, and gate verdicts."""

    record_id: str
    session_id: str
    app_name: str
    original_snippet: str
    sanitized_snippet: str
    fact_statement: str
    promotion_status: PromotionStatus
    risk_score: float
    imperative_detected: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
