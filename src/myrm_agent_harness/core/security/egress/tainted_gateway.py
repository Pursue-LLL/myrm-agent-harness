"""Transport-level egress gating and tainted data leak prevention gateway.

[INPUT]
- collections.abc::Iterable (POS: 集合迭代器抽象基类)
- contextvars::ContextVar (POS: 线程与异步上下文安全变量)
- ipaddress::ip_address (POS: IP 地址解析标准库)
- logging::logging (POS: Python 日志标准库)
- re::re (POS: 正则表达式标准库)
- urllib.parse::urlsplit (POS: URL 拆分标准库)

[OUTPUT]
- TaintedEgressDecision: Outcome enum (ALLOW_CLEAN, ALLOW_WHITELISTED, BLOCKED_TAINTED)
- TaintedEgressBlockedError: Exception raised when unapproved tainted egress is attempted
- TaintedEgressBlockedException: Backward-compatible alias for TaintedEgressBlockedError
- TaintedEgressGateway: Evaluates socket/HTTP egress against taint status and domain allowlists
- set_current_egress_tainted / is_current_egress_tainted: ContextVar helpers for transport hooks

[POS]
Core egress security layer. Bridges session-level TaintLabel.SECRET to transport layer
socket connections, replacing fragile command-string regular expressions with strict
transport-level gating across Linux, macOS, and containerized sandboxes.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Iterable
from contextvars import ContextVar
from enum import StrEnum, unique
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_TAINTED_CONTEXT: ContextVar[bool] = ContextVar("myrm_tainted_egress_context", default=False)

_LOCAL_DOMAINS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})  # noqa: S104


def set_current_egress_tainted(tainted: bool) -> None:
    """Set the tainted data status for the current execution context."""
    _TAINTED_CONTEXT.set(tainted)


def is_current_egress_tainted() -> bool:
    """Return whether the current execution context is marked as tainted."""
    return _TAINTED_CONTEXT.get()


@unique
class TaintedEgressDecision(StrEnum):
    """Evaluation result for an outbound network egress request."""

    ALLOW_CLEAN = "allow_clean"
    ALLOW_WHITELISTED = "allow_whitelisted"
    BLOCKED_TAINTED = "blocked_tainted"


class TaintedEgressBlockedError(Exception):
    """Raised when an unapproved external egress attempt occurs in a tainted session."""

    def __init__(self, host: str, port: int, reason: str) -> None:
        self.host = host
        self.port = port
        self.reason = reason
        super().__init__(f"Tainted egress blocked for {host}:{port} - {reason}")


    def format_for_user(self) -> str:
        """Format an actionable diagnostic message for user-facing audit logs."""
        return (
            f"Blocked outbound network connection to '{self.host}:{self.port}'. "
            f"The session previously accessed sensitive files or secrets. "
            f"Reason: {self.reason}"
        )


# Backward-compatible alias
TaintedEgressBlockedException = TaintedEgressBlockedError


class TaintedEgressGateway:
    """Transport-level network egress gateway enforcing taint-based leak prevention."""

    def __init__(
        self,
        static_trusted_domains: Iterable[str] | None = None,
        allow_loopback: bool = True,
    ) -> None:
        """Initialize the gateway with static trust policies.

        Args:
            static_trusted_domains: Optional list of domains exempt from taint blocking.
            allow_loopback: Whether loopback (localhost/127.0.0.1) connections are always permitted.
        """
        self._static_trusted: set[str] = {
            d.lower().strip() for d in (static_trusted_domains or []) if d and d.strip()
        }
        self._session_trusted: set[str] = set()
        self._allow_loopback = allow_loopback

    def add_session_trusted_domain(self, domain: str) -> None:
        """Exempt a domain from taint blocking for the remainder of the session.

        Args:
            domain: Target hostname or domain suffix to trust.
        """
        clean_domain = domain.lower().strip()
        if clean_domain:
            self._session_trusted.add(clean_domain)
            logger.info("Added domain '%s' to session trusted egress allowlist", clean_domain)

    def remove_session_trusted_domain(self, domain: str) -> bool:
        """Remove a previously trusted domain from the session allowlist."""
        clean_domain = domain.lower().strip()
        if clean_domain in self._session_trusted:
            self._session_trusted.remove(clean_domain)
            return True
        return False

    def list_trusted_domains(self) -> list[str]:
        """Return combined static and session-level trusted domains sorted lexicographically."""
        return sorted(list(self._static_trusted | self._session_trusted))

    def is_loopback(self, host: str) -> bool:
        """Check if target host is loopback/localhost."""
        clean_host = host.lower().strip("[]").strip()
        if clean_host in _LOCAL_DOMAINS:
            return True
        try:
            ip = ipaddress.ip_address(clean_host)
            return ip.is_loopback
        except ValueError:
            return False

    def is_domain_trusted(self, host: str) -> bool:
        """Check whether target host matches any static or session-level trusted domain."""
        clean_host = host.lower().strip("[]").strip()
        if self._allow_loopback and self.is_loopback(clean_host):
            return True

        for trusted in self._static_trusted | self._session_trusted:
            if clean_host == trusted:
                return True
            if clean_host.endswith(f".{trusted}"):
                return True
        return False

    def evaluate_egress(
        self,
        host: str,
        port: int = 443,
        is_tainted: bool | None = None,
    ) -> tuple[TaintedEgressDecision, str]:
        """Evaluate if an outbound connection to host:port is permitted.

        Args:
            host: Target hostname or IP address.
            port: Target port (default 443).
            is_tainted: Optional explicit taint flag; defaults to current ContextVar.

        Returns:
            Tuple of (TaintedEgressDecision, reason_str).
        """
        tainted = is_tainted if is_tainted is not None else is_current_egress_tainted()

        clean_host = host.lower().strip("[]").strip()
        if not clean_host:
            return TaintedEgressDecision.BLOCKED_TAINTED, "Empty target host"

        if not tainted:
            return TaintedEgressDecision.ALLOW_CLEAN, "Session is clean (untainted)"

        if self.is_domain_trusted(clean_host):
            return (
                TaintedEgressDecision.ALLOW_WHITELISTED,
                f"Host '{clean_host}' is trusted in session or static allowlist",
            )

        reason = (
            f"Host '{clean_host}' is unapproved for egress while session holds tainted data"
        )
        return TaintedEgressDecision.BLOCKED_TAINTED, reason

    def check_or_raise(
        self,
        host: str,
        port: int = 443,
        is_tainted: bool | None = None,
    ) -> None:
        """Evaluate egress and raise TaintedEgressBlockedException if blocked.

        Args:
            host: Target hostname or IP address.
            port: Target port.
            is_tainted: Optional explicit taint override.

        Raises:
            TaintedEgressBlockedException: When egress is rejected.
        """
        decision, reason = self.evaluate_egress(host, port, is_tainted)
        if decision == TaintedEgressDecision.BLOCKED_TAINTED:
            logger.warning("BLOCKED tainted egress connection: %s:%d - %s", host, port, reason)
            raise TaintedEgressBlockedException(host, port, reason)

    @staticmethod
    def extract_host_from_url(url: str) -> str:
        """Extract hostname safely from a URL or raw address."""
        if not url:
            return ""
        if "://" not in url:
            url = f"http://{url}"
        try:
            parts = urlsplit(url)
            return (parts.hostname or "").lower()
        except Exception:
            return ""

    @staticmethod
    def mask_url_for_audit(url: str) -> str:
        """Strip sensitive credentials and token query parameters for audit logs."""
        if not url:
            return ""
        try:
            parts = urlsplit(url)
            sanitized_netloc = parts.netloc
            if "@" in sanitized_netloc:
                sanitized_netloc = re.sub(r"^[^@]+@", "***:***@", sanitized_netloc)
            query = parts.query
            if query:
                # Mask common secret query keys
                query = re.sub(
                    r"(?i)(token|key|secret|password|auth|sig)=[^&]+",
                    r"\1=***",
                    query,
                )
            return parts._replace(netloc=sanitized_netloc, query=query).geturl()
        except Exception:
            return url
