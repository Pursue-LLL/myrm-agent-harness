"""
[POS] src/myrm_agent_harness/core/security/outbound_ebrake_mesh/outbound_ghost_gate.py
[INPUT] re, types
[OUTPUT] OutboundSideEffectGhostGate

Pre-flight shadow inspection gate for irreversible outbound side effects and audience domain verification.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import re

from .types import (
    AudienceRiskTier,
    GhostInspectionVerdict,
    OutboundActionType,
    OutboundEBrakeMetrics,
)


class OutboundSideEffectGhostGate:
    """Pre-flight inspection gate for audience domain boundaries and secret token leak detection."""

    # Tainted secret token patterns to detect accidental exfiltration
    SECRET_TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("OPENAI_KEY", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
        ("GITHUB_PAT", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
        ("AWS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
        ("PRIVATE_KEY", re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----")),
        ("GENERIC_PASSWORD", re.compile(r"(?:password|passwd|secret)\s*[:=]\s*['\"]?\S{6,}['\"]?", re.IGNORECASE)),
    )

    DEFAULT_INTERNAL_DOMAINS: tuple[str, ...] = (
        "myrm.internal",
        "corp.internal",
        "localhost",
        "127.0.0.1",
    )

    DEFAULT_TRUSTED_EXTERNAL_DOMAINS: tuple[str, ...] = (
        "api.github.com",
        "slack.com",
        "teams.microsoft.com",
        "calendar.google.com",
    )

    def __init__(
        self,
        internal_domains: tuple[str, ...] | None = None,
        trusted_external_domains: tuple[str, ...] | None = None,
        metrics: OutboundEBrakeMetrics | None = None,
    ) -> None:
        self._internal_domains = internal_domains or self.DEFAULT_INTERNAL_DOMAINS
        self._trusted_external_domains = (
            trusted_external_domains or self.DEFAULT_TRUSTED_EXTERNAL_DOMAINS
        )
        self._metrics = metrics if metrics is not None else OutboundEBrakeMetrics()

    @property
    def metrics(self) -> OutboundEBrakeMetrics:
        """Operational metrics reference."""
        return self._metrics

    @staticmethod
    def _extract_host_or_domain(destination: str) -> str:
        """Extract clean hostname or email domain from arbitrary destination string."""
        cleaned = destination.strip().lower()
        if "@" in cleaned:
            return cleaned.split("@")[-1].strip()
        if "://" in cleaned:
            from urllib.parse import urlparse

            return (urlparse(cleaned).hostname or "").strip()
        return cleaned.split("/")[0].split(":")[0].strip()

    def _classify_audience(self, destination: str) -> AudienceRiskTier:
        """Classify audience risk tier based on destination domain boundaries."""
        target_host = self._extract_host_or_domain(destination)

        # Check internal safe domains
        for internal in self._internal_domains:
            if target_host == internal or target_host.endswith("." + internal):
                return AudienceRiskTier.INTERNAL_SAFE

        # Check trusted external domains
        for trusted in self._trusted_external_domains:
            if target_host == trusted or target_host.endswith("." + trusted):
                return AudienceRiskTier.EXTERNAL_TRUSTED

        return AudienceRiskTier.EXTERNAL_UNTRUSTED

    def _scan_tainted_tokens(self, text: str) -> list[str]:
        """Scan payload text for sensitive credentials or keys."""
        detected: list[str] = []
        for name, pattern in self.SECRET_TOKEN_PATTERNS:
            if pattern.search(text):
                detected.append(name)
        return detected

    def inspect_outbound_action(
        self,
        action_type: OutboundActionType,
        destination_target: str,
        payload_text: str,
    ) -> GhostInspectionVerdict:
        """Perform pre-flight shadow inspection on outbound side effect."""
        self._metrics.inspections_total += 1
        tier = self._classify_audience(destination_target)
        tainted = self._scan_tainted_tokens(payload_text)

        # If secrets detected and destination is not strictly internal, block outright
        if tainted and tier != AudienceRiskTier.INTERNAL_SAFE:
            self._metrics.blocked_by_ghost_gate_total += 1
            return GhostInspectionVerdict(
                is_safe_to_queue=False,
                risk_tier=AudienceRiskTier.PROHIBITED_LEAK,
                tainted_tokens_detected=tuple(tainted),
                ghost_summary=f"Blocked exfiltration to {destination_target} with detected secrets: {tainted}",
                diagnostic_reason=f"Payload contains sensitive tokens {tainted} targeted to non-internal recipient",
            )

        # For external untrusted recipients, generate a cautionary warning summary
        if tier == AudienceRiskTier.EXTERNAL_UNTRUSTED:
            summary = (
                f"Ghost Run: Irreversible {action_type.value} to untrusted external destination "
                f"'{destination_target}' (payload size: {len(payload_text)} chars)"
            )
            return GhostInspectionVerdict(
                is_safe_to_queue=True,
                risk_tier=AudienceRiskTier.EXTERNAL_UNTRUSTED,
                tainted_tokens_detected=tuple(tainted),
                ghost_summary=summary,
                diagnostic_reason="Safe to queue into grace buffer with elevated external risk rating",
            )

        summary = (
            f"Ghost Run: {action_type.value} to {tier.value} destination '{destination_target}'"
        )
        return GhostInspectionVerdict(
            is_safe_to_queue=True,
            risk_tier=tier,
            tainted_tokens_detected=tuple(tainted),
            ghost_summary=summary,
            diagnostic_reason="Payload passed boundary domain and secret token verifications",
        )
