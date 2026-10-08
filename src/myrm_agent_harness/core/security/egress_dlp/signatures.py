"""Telemetry signature database and host normalizer.

[INPUT]
- Raw egress strings, domains, URLs, and dependency names.

[OUTPUT]
- Canonical host strings, homoglyph / CIDR evasion detection, and matched TelemetrySignature instances.

[POS]
- Harness security core knowledge base for third-party telemetry detection.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Final

from myrm_agent_harness.core.security.egress_dlp.types import (
    DLPVerdict,
    TelemetryRiskLevel,
    TelemetrySignature,
)

_TELEMETRY_DB: Final[tuple[TelemetrySignature, ...]] = (
    TelemetrySignature(
        target_domain="crewai.com",
        framework_name="CrewAI",
        risk_level=TelemetryRiskLevel.CRITICAL,
        description="CrewAI silent execution and framework telemetry collector.",
    ),
    TelemetrySignature(
        target_domain="posthog.com",
        framework_name="PostHog",
        risk_level=TelemetryRiskLevel.CRITICAL,
        description="Product analytics and user prompt telemetry tracking platform.",
    ),
    TelemetrySignature(
        target_domain="sentry.io",
        framework_name="Sentry",
        risk_level=TelemetryRiskLevel.HIGH,
        description="Error and performance tracing pipeline frequently transmitting context payloads.",
    ),
    TelemetrySignature(
        target_domain="mixpanel.com",
        framework_name="Mixpanel",
        risk_level=TelemetryRiskLevel.HIGH,
        description="User activity and behavioral event ingestion service.",
    ),
    TelemetrySignature(
        target_domain="amplitude.com",
        framework_name="Amplitude",
        risk_level=TelemetryRiskLevel.HIGH,
        description="Digital behavioral analytics pipeline.",
    ),
    TelemetrySignature(
        target_domain="segment.io",
        framework_name="Segment",
        risk_level=TelemetryRiskLevel.HIGH,
        description="Customer data platform multiplexer.",
    ),
    TelemetrySignature(
        target_domain="statsig.com",
        framework_name="Statsig",
        risk_level=TelemetryRiskLevel.MEDIUM,
        description="Feature flag and experimentation event collector.",
    ),
    TelemetrySignature(
        target_domain="datadoghq.com",
        framework_name="Datadog",
        risk_level=TelemetryRiskLevel.HIGH,
        description="Cloud observability and APM telemetry ingestion endpoint.",
    ),
)

_KNOWN_TELEMETRY_PACKAGES: Final[tuple[str, ...]] = (
    "posthog",
    "sentry-sdk",
    "mixpanel",
    "amplitude-analytics",
    "segment-analytics-python",
    "statsig",
)

_CIDR_PATTERN = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")


class TelemetrySignatureRegistry:
    """Registry maintaining domain signatures and evasion detection logic."""

    @classmethod
    def list_signatures(cls) -> tuple[TelemetrySignature, ...]:
        """Return all registered telemetry signatures."""
        return _TELEMETRY_DB

    @classmethod
    def list_known_packages(cls) -> tuple[str, ...]:
        """Return all tracked telemetry dependency package names."""
        return _KNOWN_TELEMETRY_PACKAGES

    @classmethod
    def normalize_host(cls, raw: str) -> tuple[str, DLPVerdict | None]:
        """Normalize raw destination string and detect evasion tricks (homoglyphs, CIDR bypass)."""
        s = raw.strip()
        if not s:
            return "", None

        # Detect illegal control characters
        if any(ord(c) < 32 or ord(c) == 127 for c in s):
            return "", DLPVerdict.BLOCKED_HOMOGLYPH_EVASION

        # Detect non-ASCII (homoglyph/punycode evasion attempts)
        if any(ord(c) > 127 for c in s):
            return "", DLPVerdict.BLOCKED_HOMOGLYPH_EVASION

        # Detect CIDR subnet bypass attempt in domain slot
        if _CIDR_PATTERN.match(s) or ("/" in s and not s.startswith(("http://", "https://"))):
            return "", DLPVerdict.BLOCKED_CIDR_BYPASS

        # URL extraction if scheme present
        if "://" in s:
            parsed = urllib.parse.urlparse(s)
            s = parsed.hostname or ""
        elif "/" in s:
            s = s.split("/", 1)[0]

        # Port stripping
        if ":" in s:
            s = s.split(":", 1)[0]

        normalized = s.lower().strip()
        if normalized.startswith("*."):
            normalized = normalized[2:]
        if normalized.endswith("."):
            normalized = normalized[:-1]

        return normalized, None

    @classmethod
    def match_host(cls, host: str) -> TelemetrySignature | None:
        """Find matching telemetry signature for a normalized host."""
        if not host:
            return None
        for sig in _TELEMETRY_DB:
            domain = sig.target_domain
            if host == domain or host.endswith(f".{domain}"):
                return sig
        return None

    @classmethod
    def match_package(cls, package_name: str) -> bool:
        """Check if package name is a tracked telemetry SDK."""
        lowered = package_name.lower().replace("_", "-")
        return any(lowered == pkg or lowered.startswith(f"{pkg}[") for pkg in _KNOWN_TELEMETRY_PACKAGES)
