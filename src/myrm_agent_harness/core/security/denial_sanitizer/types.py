"""Type definitions for gate guard denial path Unicode sanitization.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and models for denial message sanitization and spoofing analysis.

[POS]
- Harness core security module sanitizing denial error paths to prevent zero-width bypass and UI spoofing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SpoofRiskLevel(StrEnum):
    """Assessment of text spoofing risk due to invisible or bidirectional codepoints."""

    NONE = "NONE"
    LOW = "LOW"
    HIGH = "HIGH"


@dataclass(frozen=True)
class DenialSanitizeResult:
    """Outcome of sanitizing a gate guard denial reason or payload."""

    original_text: str
    sanitized_text: str
    invisible_codepoints_removed: int
    has_bidi_controls: bool
    spoof_risk: SpoofRiskLevel
    removed_characters: list[str] = field(default_factory=list)
