"""Zero-Egress Guard enforcing network containment and cryptographic audit proof.

[INPUT]
- destination_host, destination_port, protocol, EgressControlTier

[OUTPUT]
- ZeroEgressGuard: enforces strict loopback-only isolation in air-gapped sovereign mode.
- ZeroEgressAssertionResult: cryptographically hashed audit assertion of zero egress.

[POS]
Harness core security subsystem for sovereign air-gapped deployments and network isolation.
"""

from __future__ import annotations

import hashlib
import ipaddress
import threading
import time
import uuid

from myrm_agent_harness.core.security.air_gapped.types import (
    EgressAttemptRecord,
    EgressControlTier,
    ExternalEgressBlockedError,
    ZeroEgressAssertionResult,
)

_LOOPBACK_HOSTS: frozenset[str] = frozenset(
    {"localhost", "127.0.0.1", "::1", "unix"}
)


def _is_loopback(host: str) -> bool:
    """Determine whether destination host is strictly local loopback."""
    clean_host = host.strip().lower()
    if clean_host in _LOOPBACK_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(clean_host)
        return ip.is_loopback
    except ValueError:
        return False


def _is_private_network(host: str) -> bool:
    """Determine whether destination host is within RFC1918 private network space."""
    clean_host = host.strip().lower()
    if _is_loopback(clean_host):
        return True
    try:
        ip = ipaddress.ip_address(clean_host)
        return ip.is_private
    except ValueError:
        return False


class ZeroEgressGuard:
    """Network egress filter enforcing air-gapped sovereign and conservative policies."""

    def __init__(
        self,
        tier: EgressControlTier = EgressControlTier.AIR_GAPPED_SOVEREIGN,
        allowlist_domains: set[str] | None = None,
    ) -> None:
        self._tier = tier
        self._allowlist_domains = set(allowlist_domains) if allowlist_domains else set()
        self._records: list[EgressAttemptRecord] = []
        self._lock = threading.Lock()

    @property
    def tier(self) -> EgressControlTier:
        """Active egress control tier."""
        with self._lock:
            return self._tier

    def set_tier(self, tier: EgressControlTier) -> None:
        """Switch operational egress tier."""
        with self._lock:
            self._tier = tier

    def check_destination(
        self,
        host: str,
        port: int,
        protocol: str = "tcp",
    ) -> tuple[bool, str]:
        """Inspect proposed outbound connection against active tier policy."""
        clean_host = host.strip().lower()
        with self._lock:
            current_tier = self._tier

        # 1. Sovereign Air-Gapped Mode: Absolute zero external egress, loopback only
        if current_tier == EgressControlTier.AIR_GAPPED_SOVEREIGN:
            if _is_loopback(clean_host):
                return True, "Loopback connection allowed in air-gapped sovereign mode"
            return (
                False,
                f"Air-Gapped Sovereign Violation: External destination '{clean_host}:{port}' strictly forbidden",
            )

        # 2. Conservative Mode: Loopback and private internal network permitted, external requires allowlist
        if current_tier == EgressControlTier.CONSERVATIVE:
            if _is_private_network(clean_host):
                return True, "Internal private network connection authorized"
            if clean_host in self._allowlist_domains:
                return True, "Destination permitted by explicit domain allowlist"
            return (
                False,
                f"Conservative Egress Policy: Non-allowlisted external destination '{clean_host}' held fail-closed",
            )

        # 3. Standard Mode: Allowlisted destinations or non-blocked
        if clean_host in self._allowlist_domains or _is_private_network(clean_host):
            return True, "Destination authorized in standard tier"
        return True, "Standard egress permitted by default policy"

    def record_and_assert(
        self,
        host: str,
        port: int,
        protocol: str = "tcp",
    ) -> EgressAttemptRecord:
        """Check destination, record telemetry, and raise ExternalEgressBlockedError if denied."""
        allowed, reason = self.check_destination(host, port, protocol)
        attempt_id = f"egr_{uuid.uuid4().hex[:10]}"

        with self._lock:
            current_tier = self._tier
            record = EgressAttemptRecord(
                attempt_id=attempt_id,
                destination_host=host,
                destination_port=port,
                protocol=protocol,
                allowed=allowed,
                reason=reason,
                tier=current_tier,
                timestamp=time.time(),
            )
            self._records.append(record)

        if not allowed:
            raise ExternalEgressBlockedError(host, port, reason)

        return record

    def assert_zero_egress(self) -> ZeroEgressAssertionResult:
        """Compute formal cryptographic proof that 0 external connections succeeded."""
        with self._lock:
            records = list(self._records)

        external_egress_count = 0
        blocked_count = 0

        for r in records:
            if not r.allowed:
                blocked_count += 1
            elif not _is_loopback(r.destination_host):
                external_egress_count += 1

        is_compliant = external_egress_count == 0

        # Construct deterministic hash digest over history
        history_repr = "|".join(
            f"{r.attempt_id}:{r.destination_host}:{r.destination_port}:{r.allowed}"
            for r in records
        )
        assertion_hash = hashlib.sha256(history_repr.encode("utf-8")).hexdigest()

        return ZeroEgressAssertionResult(
            total_attempts=len(records),
            blocked_attempts=blocked_count,
            external_egress_count=external_egress_count,
            is_zero_egress_compliant=is_compliant,
            assertion_hash=assertion_hash,
            verified_at=time.time(),
        )

    def list_attempts(self, limit: int = 100) -> list[EgressAttemptRecord]:
        """Return recent egress attempts in reverse chronological order."""
        with self._lock:
            recs = list(self._records)
        recs.reverse()
        return recs[:limit]

    def clear_attempts(self) -> None:
        """Wipe attempt history."""
        with self._lock:
            self._records.clear()
