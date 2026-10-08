"""Host and Origin guard to prevent DNS rebinding and cross-site hijacking."""

from __future__ import annotations

from urllib.parse import urlparse

from .types import HostOriginPolicy, ValidationResult


class HostOriginGuard:
    """Verifies incoming HTTP and WebSocket requests against DNS rebinding

    and unauthorized cross-origin access.
    """

    def __init__(self, policy: HostOriginPolicy | None = None) -> None:
        self._policy: HostOriginPolicy = policy or HostOriginPolicy()

    @property
    def policy(self) -> HostOriginPolicy:
        """Get current policy configuration."""
        return self._policy

    def _extract_hostname(self, host_str: str) -> str:
        """Extract clean hostname from host string, handling IPv6 brackets and ports."""
        host_str = host_str.strip().lower()
        if host_str.startswith("["):
            # IPv6 address with port: [::1]:8000 -> [::1]
            bracket_end = host_str.find("]")
            if bracket_end != -1:
                return host_str[: bracket_end + 1]
            return host_str

        # IPv4 or regular hostname: 127.0.0.1:8000 -> 127.0.0.1
        if ":" in host_str:
            return host_str.split(":", 1)[0]
        return host_str

    def is_host_allowed(self, host_header: str | None) -> bool:
        """Check if Host header represents a trusted local host."""
        if not host_header:
            return not self._policy.enforce_strict_mode

        hostname = self._extract_hostname(host_header)
        for allowed in self._policy.allowed_hosts:
            clean_allowed = self._extract_hostname(allowed)
            if hostname == clean_allowed:
                return True
        return False

    def is_origin_allowed(self, origin_header: str | None) -> bool:
        """Check if Origin header is allowed under the policy."""
        if not origin_header:
            # If no Origin is present, it is not a CORS request
            return True

        origin_clean = origin_header.strip().lower()
        if origin_clean == "null":
            return self._policy.allow_null_origin

        # Match against configured allowed origins
        parsed = urlparse(origin_clean)
        origin_scheme = parsed.scheme
        origin_host = self._extract_hostname(parsed.netloc)

        for allowed in self._policy.allowed_origins:
            if origin_clean == allowed.lower():
                return True
            try:
                allowed_parsed = urlparse(allowed.lower())
                # If scheme matches, host matches, and allowed doesn't specify a port or matches port
                if (
                    allowed_parsed.scheme == origin_scheme
                    and self._extract_hostname(allowed_parsed.netloc) == origin_host
                    and (":" not in allowed_parsed.netloc or allowed_parsed.netloc == parsed.netloc)
                ):
                    return True
            except Exception:
                continue

        return False

    def is_referer_allowed(self, referer_header: str | None) -> bool:
        """Check if Referer header originates from an allowed host."""
        if not referer_header:
            return True

        try:
            parsed = urlparse(referer_header.strip().lower())
            referer_host = self._extract_hostname(parsed.netloc)
            for allowed_host in self._policy.allowed_hosts:
                clean_allowed = self._extract_hostname(allowed_host)
                if referer_host == clean_allowed:
                    return True
        except Exception:
            return False

        return False

    def verify_request(
        self,
        host: str | None,
        origin: str | None,
        referer: str | None = None,
        client_ip: str | None = None,
    ) -> ValidationResult:
        """Comprehensive verification of incoming request headers.

        Returns:
            ValidationResult indicating whether request is safe to proceed.
        """
        # 1. Host check (primary defense against DNS rebinding)
        if not self.is_host_allowed(host):
            return ValidationResult(
                is_allowed=False,
                status="rejected_host",
                reason=(
                    f"Host header '{host}' is not in allowed hosts whitelist; "
                    "potential DNS rebinding attack blocked."
                ),
                client_ip=client_ip,
                host_header=host,
                origin_header=origin,
                referer_header=referer,
            )

        # 2. Origin check (defense against malicious cross-origin scripts)
        if not self.is_origin_allowed(origin):
            return ValidationResult(
                is_allowed=False,
                status="rejected_origin",
                reason=(
                    f"Origin header '{origin}' is not trusted; "
                    "cross-site request blocked."
                ),
                client_ip=client_ip,
                host_header=host,
                origin_header=origin,
                referer_header=referer,
            )

        # 3. Referer check (defense against navigational CSRF when Origin is omitted)
        if origin is None and referer and not self.is_referer_allowed(referer):
            return ValidationResult(
                is_allowed=False,
                status="rejected_referer",
                reason=(
                    f"Referer header '{referer}' originates from untrusted domain; "
                    "potential cross-site navigation blocked."
                ),
                client_ip=client_ip,
                host_header=host,
                origin_header=origin,
                referer_header=referer,
            )

        return ValidationResult(
            is_allowed=True,
            status="allowed",
            reason="Request host and origin verified safe.",
            client_ip=client_ip,
            host_header=host,
            origin_header=origin,
            referer_header=referer,
        )
