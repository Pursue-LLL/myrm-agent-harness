"""Gate guard denial path Unicode sanitization module.

[INPUT]
- Denial messages or dictionary payloads containing potentially malicious text.

[OUTPUT]
- DenialSanitizeResult with stripped text, codepoint metrics, and spoof risk rating.

[POS]
- Harness core security module preventing invisible Unicode bypass and UI spoofing.
"""

from __future__ import annotations

from .sanitizer import sanitize_denial_message, sanitize_denial_payload
from .types import DenialSanitizeResult, SpoofRiskLevel

__all__ = [
    "DenialSanitizeResult",
    "SpoofRiskLevel",
    "sanitize_denial_message",
    "sanitize_denial_payload",
]
