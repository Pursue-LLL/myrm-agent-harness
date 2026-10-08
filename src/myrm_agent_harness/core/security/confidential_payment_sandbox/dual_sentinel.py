"""
[POS] src/myrm_agent_harness/core/security/confidential_payment_sandbox/dual_sentinel.py
[INPUT] re, types
[OUTPUT] DualDirectionSecuritySentinel
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re

from .types import (
    DualSentinelScanResult,
    IngressFenceMode,
)

logger = logging.getLogger(__name__)

# Heuristic patterns for Ingress Prompt Injections
_INGRESS_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"system\s+override", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:in\s+)?developer\s+mode", re.IGNORECASE),
    re.compile(r"dump\s+(?:all\s+)?(?:system\s+)?(?:secrets?|credentials?|passwords?)", re.IGNORECASE),
    re.compile(r"bypass\s+(?:security\s+)?(?:fence|guardrail|checks?)", re.IGNORECASE),
)

# Regex patterns for Egress Secret Exfiltrations (Plain Credit Cards and Private Keys)
_EGRESS_CARD_REGEX = re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b")
_EGRESS_PRIVATE_KEY_REGEX = re.compile(r"-----BEGIN\s+(?:[A-Z\s]+)?PRIVATE\s+KEY-----", re.IGNORECASE)


class DualDirectionSecuritySentinel:
    """Inspects ingress/egress message streams and enforces default read-only fences on external services."""

    def __init__(self) -> None:
        pass

    def scan_ingress(self, content: str) -> DualSentinelScanResult:
        """Inspect inbound user or external payload for prompt injection vectors."""
        threats: list[str] = []
        for pat in _INGRESS_INJECTION_PATTERNS:
            if pat.search(content):
                threats.append(pat.pattern)

        is_blocked = len(threats) > 0
        diagnostic = (
            f"Blocked ingress prompt injection attempt: detected {len(threats)} vectors"
            if is_blocked
            else "Ingress content verified benign"
        )

        return DualSentinelScanResult(
            direction="ingress",
            is_blocked=is_blocked,
            detected_threats=tuple(threats),
            sanitized_content="[BLOCKED_PROMPT_INJECTION]" if is_blocked else content,
            diagnostic=diagnostic,
        )

    def scan_egress(self, content: str) -> DualSentinelScanResult:
        """Inspect outbound message stream for plain card details or private keys."""
        threats: list[str] = []
        sanitized = content

        # Check credit cards
        if _EGRESS_CARD_REGEX.search(content):
            threats.append("PLAIN_CREDIT_CARD_NUMBER")
            sanitized = _EGRESS_CARD_REGEX.sub("[REDACTED_CARD_NUMBER]", sanitized)

        # Check private keys
        if _EGRESS_PRIVATE_KEY_REGEX.search(content):
            threats.append("PRIVATE_KEY_EXFILTRATION")
            sanitized = _EGRESS_PRIVATE_KEY_REGEX.sub("[REDACTED_PRIVATE_KEY]", sanitized)

        is_blocked = len(threats) > 0
        diagnostic = (
            f"Blocked outbound exfiltration: detected {len(threats)} sensitive patterns"
            if is_blocked
            else "Egress content verified clean"
        )

        return DualSentinelScanResult(
            direction="egress",
            is_blocked=is_blocked,
            detected_threats=tuple(threats),
            sanitized_content=sanitized,
            diagnostic=diagnostic,
        )

    def check_external_channel_access(
        self,
        channel_name: str,
        action_type: str,  # "read" or "write"
        fence_mode: IngressFenceMode = IngressFenceMode.READ_ONLY,
    ) -> tuple[bool, str]:
        """Enforce default read-only barrier on external channels (Email, IMAP, Drive)."""
        action_clean = action_type.strip().lower()

        if action_clean == "read":
            return True, f"Read access to channel '{channel_name}' permitted"

        if fence_mode != IngressFenceMode.ELEVATED_WRITE_PERMITTED:
            return (
                False,
                f"Write access to channel '{channel_name}' blocked: external channels are default READ_ONLY",
            )

        return True, f"Write access to channel '{channel_name}' permitted under elevated consent"
