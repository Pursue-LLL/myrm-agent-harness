# [POS] src/myrm_agent_harness/toolkits/memory/vector_preflight/sanitizer.py
# [INPUT] urllib.parse, re, logging, .types (SanitizedEndpointResult)
# [OUTPUT] IPv4LoopbackSanitizer

import logging
import re
from urllib.parse import urlparse, urlunparse

from .types import SanitizedEndpointResult

logger = logging.getLogger(__name__)

# Pattern detecting loopback identifiers prone to IPv6 resolution trap (::1 or localhost)
_LOOPBACK_TARGETS: tuple[str, ...] = ("localhost", "::1", "[::1]")
_IPV4_LOOPBACK: str = "127.0.0.1"


class IPv4LoopbackSanitizer:
    """Sanitizes connection endpoints to eliminate IPv6 ::1 localhost resolution traps in container environments."""

    @classmethod
    def sanitize_host(cls, host: str) -> tuple[str, bool, str]:
        """Normalize host string to IPv4 loopback if it points to localhost or IPv6 loopback.

        Returns:
            Tuple of (sanitized_host, was_modified, reason).
        """
        clean_host = host.strip()
        lower_host = clean_host.lower()

        if lower_host in _LOOPBACK_TARGETS:
            reason = (
                f"Normalized loopback host '{clean_host}' to IPv4 '{_IPV4_LOOPBACK}' "
                "to prevent IPv6 ::1 container connection 503/timeout failures."
            )
            return _IPV4_LOOPBACK, True, reason

        return clean_host, False, ""

    @classmethod
    def sanitize_endpoint(cls, endpoint: str) -> SanitizedEndpointResult:
        """Sanitize a full or partial URI/endpoint string (e.g. 'http://localhost:6333', 'localhost:6333')."""
        raw = endpoint.strip()
        if not raw:
            return SanitizedEndpointResult(
                raw_endpoint="",
                sanitized_endpoint="",
                was_modified=False,
                modification_reason="Empty endpoint string.",
            )

        # Check if scheme is present (e.g. http://, grpc://)
        has_scheme = bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw))
        parse_target = raw if has_scheme else f"tcp://{raw}"

        try:
            parsed = urlparse(parse_target)
            hostname = parsed.hostname
            if not hostname:
                return SanitizedEndpointResult(
                    raw_endpoint=raw,
                    sanitized_endpoint=raw,
                    was_modified=False,
                    modification_reason="Could not extract hostname from endpoint.",
                )

            sanitized_host, modified, reason = cls.sanitize_host(hostname)
            if not modified:
                return SanitizedEndpointResult(
                    raw_endpoint=raw,
                    sanitized_endpoint=raw,
                    was_modified=False,
                    modification_reason="",
                )

            # Reconstruct netloc with port and user credentials if present
            port_str = f":{parsed.port}" if parsed.port is not None else ""
            userinfo = ""
            if parsed.username:
                userinfo = parsed.username
                if parsed.password:
                    userinfo += f":{parsed.password}"
                userinfo += "@"

            new_netloc = f"{userinfo}{sanitized_host}{port_str}"

            if has_scheme:
                reconstructed = urlunparse((
                    parsed.scheme,
                    new_netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                ))
            else:
                reconstructed = f"{new_netloc}{parsed.path}"

            logger.info("IPv4LoopbackSanitizer: %s -> %s", raw, reconstructed)
            return SanitizedEndpointResult(
                raw_endpoint=raw,
                sanitized_endpoint=reconstructed,
                was_modified=True,
                modification_reason=reason,
            )

        except Exception as exc:
            logger.warning("Failed to parse endpoint '%s' for loopback sanitization: %s", raw, exc)
            return SanitizedEndpointResult(
                raw_endpoint=raw,
                sanitized_endpoint=raw,
                was_modified=False,
                modification_reason=f"URL parsing exception: {exc}",
            )
