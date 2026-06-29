"""Context-based URL allowlist for skill-level DLP domain restrictions.

[INPUT]
- (none)

[OUTPUT]
- SSRFSecurityError: raised when hostname violates skill allowed-domains
- URLAllowlistGuard: ContextVar-scoped domain allowlist for tool execution

[POS]
Skill DLP domain enforcement for outbound HTTP; applied by tool_executor and SSRF validators.
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class SSRFSecurityError(ValueError):
    """Raised when an SSRF or DLP allowlist violation is detected."""


_allowed_domains_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "allowed_domains", default=None
)


class URLAllowlistGuard:
    """Context-based URL allowlist for DLP protection."""

    @staticmethod
    @contextmanager
    def apply(allowed_domains: list[str] | None):
        """Apply allowlist to current async context."""
        token = _allowed_domains_var.set(allowed_domains)
        try:
            yield
        finally:
            _allowed_domains_var.reset(token)

    @staticmethod
    def check(hostname: str) -> None:
        """Check if hostname is in the current context's allowlist."""
        allowed_domains = _allowed_domains_var.get()
        if allowed_domains is None:
            return

        for domain in allowed_domains:
            if domain == "*":
                return
            if hostname == domain or hostname.endswith(f".{domain}"):
                return

        logger.warning("DLP Shield blocked request to unauthorized domain: %s", hostname)
        raise SSRFSecurityError(
            f"Access to {hostname} is blocked. "
            f"The current skill is only allowed to access: {', '.join(allowed_domains)}"
        )
