"""GateGuard denial path Unicode sanitization module.

[INPUT]
- Untrusted paths, parameters, or denial reasons.

[OUTPUT]
- Sanitized strings protected against invisible Unicode and UI spoofing.

[POS]
- Harness security subsystem for denial-path sanitization (#3103).
"""

from __future__ import annotations

from .sanitizer import (
    GateGuardDenialSanitizer,
    sanitize_denial_path,
    sanitize_denial_reason,
)
from .types import (
    DenialSanitizePolicy,
    InvisibleUnicodeCategory,
    SanitizeResult,
)
from .unicode_policy import (
    DANGEROUS_DENIAL_UNICODE_RE,
    classify_codepoint,
    detect_categories,
)

__all__ = [
    "DANGEROUS_DENIAL_UNICODE_RE",
    "DenialSanitizePolicy",
    "GateGuardDenialSanitizer",
    "InvisibleUnicodeCategory",
    "SanitizeResult",
    "classify_codepoint",
    "detect_categories",
    "sanitize_denial_path",
    "sanitize_denial_reason",
]
