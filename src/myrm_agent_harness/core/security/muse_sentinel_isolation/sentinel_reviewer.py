"""Sentinel Pre-Outbound Traffic Reviewer Watchdog.

Inspects all egress traffic frames before leaving the isolated sandbox VM environment,
preventing raw credential leakage, token exfiltration, and unauthorized network calls.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .types import (
    OutboundTrafficPayload,
    SentinelReviewResult,
    SentinelVerdict,
)

_SECRET_LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b")),
    ("stripe_live_key", re.compile(r"\b(?:sk_live_|rk_live_)[0-9a-zA-Z]{24,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("private_key_header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]

_SUSPICIOUS_EXFILTRATION_HOSTS: frozenset[str] = frozenset({
    "pastebin.com",
    "transfer.sh",
    "webhook.site",
    "ngrok.io",
    "ngrok-free.app",
    "file.io",
})


class SentinelOutboundReviewer:
    """Independent security watchdog inspecting outbound network payloads before internet dispatch."""

    def __init__(
        self,
        blocked_hosts: set[str] | None = None,
        challenge_hosts: set[str] | None = None,
    ) -> None:
        self._blocked_hosts = set(_SUSPICIOUS_EXFILTRATION_HOSTS)
        if blocked_hosts:
            self._blocked_hosts.update(h.lower() for h in blocked_hosts)
        self._challenge_hosts = set(challenge_hosts or set())

    def review_outbound_traffic(
        self, payload: OutboundTrafficPayload
    ) -> SentinelReviewResult:
        """Analyze outbound request for secret leaks, untrusted destinations, and exfiltration attempts."""
        # 1. Inspect headers and body for raw credential leakage
        for rule_name, pattern in _SECRET_LEAK_PATTERNS:
            for header_name, header_val in payload.headers.items():
                if pattern.search(header_val):
                    return SentinelReviewResult(
                        request_id=payload.request_id,
                        verdict=SentinelVerdict.BLOCK,
                        matched_rule=f"secret_leak_header_{rule_name}",
                        reason=(
                            f"Sentinel blocked outbound traffic: raw secret matching '{rule_name}' "
                            f"detected in header '{header_name}'"
                        ),
                        risk_score=1.0,
                    )

            if pattern.search(payload.body_preview):
                return SentinelReviewResult(
                    request_id=payload.request_id,
                    verdict=SentinelVerdict.BLOCK,
                    matched_rule=f"secret_leak_body_{rule_name}",
                    reason=(
                        f"Sentinel blocked outbound traffic: raw secret matching '{rule_name}' "
                        "detected in request body"
                    ),
                    risk_score=1.0,
                )

        # 2. Inspect target destination host
        hostname = self._extract_hostname(payload.destination_url)
        if hostname in self._blocked_hosts:
            return SentinelReviewResult(
                request_id=payload.request_id,
                verdict=SentinelVerdict.BLOCK,
                matched_rule="blocked_exfiltration_host",
                reason=(
                    f"Sentinel blocked outbound traffic: destination '{hostname}' is on the "
                    "known exfiltration / tunnel deny list"
                ),
                risk_score=0.95,
            )

        if hostname in self._challenge_hosts:
            return SentinelReviewResult(
                request_id=payload.request_id,
                verdict=SentinelVerdict.REQUIRE_CHALLENGE,
                matched_rule="challenge_required_destination",
                reason=(
                    f"Sentinel flagged outbound traffic: destination '{hostname}' requires "
                    "explicit user challenge verification"
                ),
                risk_score=0.6,
            )

        # 3. Safe outbound traffic authorized
        return SentinelReviewResult(
            request_id=payload.request_id,
            verdict=SentinelVerdict.ALLOW,
            matched_rule=None,
            reason="Sentinel passed: no credential leak or exfiltration threat identified",
            risk_score=0.0,
        )

    def add_blocked_host(self, host: str) -> None:
        """Add hostname to blocked egress list."""
        self._blocked_hosts.add(host.lower().strip())

    def add_challenge_host(self, host: str) -> None:
        """Add hostname to challenge-required egress list."""
        self._challenge_hosts.add(host.lower().strip())

    @staticmethod
    def _extract_hostname(url: str) -> str:
        """Extract lowercase hostname from URL string."""
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.hostname or url
        return host.lower()
