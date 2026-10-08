"""Type definitions for Data Plane Injection Defense and Hardened Data Fencing.

[INPUT]
None.

[OUTPUT]
- InjectionPlaneType, SanitizedQuoteResult, DataPlaneThreatFinding
- DataPlaneSecurityError, HardenedFenceViolationError

[POS]
Harness core security subsystem inspired by Anthropic Commerce Agents (fencing.py & QuotedAsData).
Defends against indirect prompt injections planted in tool results and third-party content.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class InjectionPlaneType(StrEnum):
    """Separation of prompt injection attack surfaces."""

    USER_PLANE = "user_plane"  # Direct jailbreak or prompt override in user's prompt
    DATA_PLANE = "data_plane"  # Indirect prompt injection embedded in external data/tool output


@dataclass(frozen=True, slots=True)
class DataPlaneThreatFinding:
    """Specific threat or forged turn marker neutralized during fencing."""

    threat_type: str
    pattern_matched: str
    raw_snippet: str
    sanitized_replacement: str


@dataclass(frozen=True, slots=True)
class SanitizedQuoteResult:
    """Outcome of hardened data fencing, including sanitized text and threat telemetry."""

    sanitized_text: str
    enclosed_payload: str
    subject: str
    source: str
    original_length: int
    sanitized_length: int
    stripped_turns_count: int
    removed_control_chars_count: int
    is_truncated: bool
    findings: tuple[DataPlaneThreatFinding, ...] = ()
    sanitized_at: float = field(default_factory=time.time)


class DataPlaneSecurityError(Exception):
    """Base exception for data plane defense violations."""


class HardenedFenceViolationError(DataPlaneSecurityError):
    """Raised when external data payload contains unrecoverable or malicious structures."""
