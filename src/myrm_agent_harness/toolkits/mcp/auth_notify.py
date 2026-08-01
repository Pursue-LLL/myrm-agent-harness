"""MCP auth-expiry notification hook (toolkit layer — no runtime imports).

[INPUT]
- register_mcp_auth_expired_handler: Callable[[str, str], None] from runtime wiring
- core.security.redact::redact_sensitive_text (POS: Regex-based secret redaction for API keys, tokens, passwords)

[OUTPUT]
- register_mcp_auth_expired_handler: Register a callback for OAuth expiry
- notify_mcp_auth_expired: Invoke registered handlers (best-effort, error_detail redacted)

[POS]
Decouples MCP toolkit from runtime EventBus while preserving auth-expiry UX.
Runtime registers the handler that publishes MCPAuthExpiredEvent at import time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from myrm_agent_harness.core.security.redact import redact_sensitive_text

logger = logging.getLogger(__name__)

AuthExpiredHandler = Callable[[str, str], None]

_handlers: list[AuthExpiredHandler] = []


def register_mcp_auth_expired_handler(handler: AuthExpiredHandler) -> None:
    """Register a handler invoked when MCP OAuth credentials appear expired."""
    _handlers.append(handler)


def notify_mcp_auth_expired(server_name: str, error_detail: str) -> None:
    """Notify all registered handlers (errors are logged, never raised)."""
    safe_detail = redact_sensitive_text(error_detail)
    for handler in _handlers:
        try:
            handler(server_name, safe_detail)
        except Exception:
            logger.debug(
                "MCP auth-expired handler failed for '%s'",
                server_name,
                exc_info=True,
            )
