"""Sanitize compile error messages before exposing them in API/UI.

[INPUT]
- core.security.persistence.content_scan::sanitize_display_secrets (POS: credential redaction SSOT)

[OUTPUT]
- sanitize_display_message: redact credential fragments and truncate user-visible errors

[POS]
Wiki compile error sanitizer. Strips API key patterns before queue/API/UI display.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.persistence.content_scan import sanitize_display_secrets


def sanitize_display_message(message: str, *, max_length: int = 240) -> str:
    """Return a user-safe, truncated error summary without credential fragments."""
    return sanitize_display_secrets(message, max_length=max_length)
