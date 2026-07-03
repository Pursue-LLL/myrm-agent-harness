"""MCP auth-expiry notification hook (toolkit layer — no runtime imports).

[INPUT]
- register_mcp_auth_expired_handler: Callable[[str, str], None] from runtime wiring

[OUTPUT]
- register_mcp_auth_expired_handler: Register a callback for OAuth expiry
- notify_mcp_auth_expired: Invoke registered handlers (best-effort)

[POS]
Decouples MCP toolkit from runtime EventBus while preserving auth-expiry UX.
Runtime registers the handler that publishes MCPAuthExpiredEvent at import time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

AuthExpiredHandler = Callable[[str, str], None]

_handlers: list[AuthExpiredHandler] = []


def register_mcp_auth_expired_handler(handler: AuthExpiredHandler) -> None:
    """Register a handler invoked when MCP OAuth credentials appear expired."""
    _handlers.append(handler)


def notify_mcp_auth_expired(server_name: str, error_detail: str) -> None:
    """Notify all registered handlers (errors are logged, never raised)."""
    for handler in _handlers:
        try:
            handler(server_name, error_detail)
        except Exception:
            logger.debug(
                "MCP auth-expired handler failed for '%s'",
                server_name,
                exc_info=True,
            )
