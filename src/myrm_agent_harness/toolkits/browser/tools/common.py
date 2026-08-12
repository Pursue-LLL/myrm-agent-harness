"""Shared utilities for browser tools.

[INPUT]
- agent.security.detection.content_boundary::wrap_untrusted (POS: 4-layer defense content boundary)
- core.security.redact::redact_sensitive_text (POS: Regex-based secret redaction)

[OUTPUT]
- mark_untrusted: Redact credentials, then wrap browser-sourced content with 4-layer security boundary (Unicode folding + marker sanitization + random boundary + pattern detection).

[POS]
Shared utilities for browser tools. mark_untrusted provides the unified output security
boundary (credential redaction + untrusted-content wrapping) for every browser tool result.
"""

from myrm_agent_harness.core.security.detection.content_boundary import wrap_untrusted
from myrm_agent_harness.core.security.redact import redact_sensitive_text


def mark_untrusted(content: str) -> str:
    """Redact credentials from browser-sourced content, then wrap with 4-layer security boundary.

    Redaction happens before wrapping so page-displayed API keys / tokens
    (e.g. cloud console panels, GitHub pages) never reach the LLM context or
    the persistent memory store, matching the protection already applied to
    bash / file_read / MCP tool outputs.
    """
    return wrap_untrusted(redact_sensitive_text(content), source="browser")
