"""Shared utilities for browser tools.

[INPUT]
- agent.security.detection.content_boundary::wrap_untrusted (POS: 4-layer defense content boundary)

[OUTPUT]
- mark_untrusted: Wrap browser-sourced content with 4-layer security boundary (Unicode folding + marker sanitization + random boundary + pattern detection).

[POS]
Shared utilities for browser tools.
"""

from myrm_agent_harness.core.security.detection.content_boundary import wrap_untrusted


def mark_untrusted(content: str) -> str:
    """Wrap browser-sourced content with 4-layer security boundary."""
    return wrap_untrusted(content, source="browser")
