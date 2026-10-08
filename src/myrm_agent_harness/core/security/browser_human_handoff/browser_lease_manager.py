"""
[POS] src/myrm_agent_harness/core/security/browser_human_handoff/browser_lease_manager.py
[INPUT] time, uuid, typing
[OUTPUT] BrowserProfileLeaseManager

Logged-in Browser Lease & Profile Sharing Manager.
Enforces mutual-exclusion session leases across agent tasks (Cursor, Claude Code, Myrm)
to prevent concurrent session collisions and profile corruption.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time
import uuid

from .types import BrowserLeaseStatus, BrowserProfileLease

logger = logging.getLogger(__name__)


class BrowserProfileLeaseManager:
    """Manages exclusive single-task leases on logged-in browser profiles."""

    DEFAULT_TTL_SECONDS: float = 300.0  # 5 minutes

    def __init__(self) -> None:
        self._active_leases: dict[str, BrowserProfileLease] = {}  # profile_name -> lease
        self._lease_lookup: dict[str, BrowserProfileLease] = {}  # lease_id -> lease

    def acquire_lease(
        self,
        profile_name: str,
        consumer_id: str,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> BrowserProfileLease:
        """Acquire exclusive lease lock on a logged-in browser profile."""
        now = time.time()
        existing = self._active_leases.get(profile_name)

        if existing is not None:
            # Check if existing lease has expired
            if now >= existing.acquired_at + existing.ttl_seconds:
                logger.info(
                    "Prior lease %s for profile '%s' expired. Reclaiming.",
                    existing.lease_id,
                    profile_name,
                )
                self._expire_lease(existing)
            else:
                raise RuntimeError(
                    f"Browser profile '{profile_name}' is currently leased by consumer '{existing.consumer_id}' "
                    f"until {existing.acquired_at + existing.ttl_seconds:.0f} (lease_id={existing.lease_id})."
                )

        lease_id = f"lease-{uuid.uuid4().hex[:12]}"
        new_lease = BrowserProfileLease(
            lease_id=lease_id,
            profile_name=profile_name,
            consumer_id=consumer_id,
            acquired_at=now,
            ttl_seconds=ttl_seconds,
            status=BrowserLeaseStatus.LEASED,
        )

        self._active_leases[profile_name] = new_lease
        self._lease_lookup[lease_id] = new_lease
        logger.info(
            "Granted exclusive lease %s on profile '%s' to consumer '%s' (ttl=%ds)",
            lease_id,
            profile_name,
            consumer_id,
            int(ttl_seconds),
        )
        return new_lease

    def release_lease(self, lease_id: str) -> BrowserProfileLease:
        """Release an exclusive profile lease, returning it to the pool."""
        lease = self._lease_lookup.get(lease_id)
        if lease is None:
            raise KeyError(f"Browser profile lease '{lease_id}' not found.")

        released_lease = BrowserProfileLease(
            lease_id=lease.lease_id,
            profile_name=lease.profile_name,
            consumer_id=lease.consumer_id,
            acquired_at=lease.acquired_at,
            ttl_seconds=lease.ttl_seconds,
            status=BrowserLeaseStatus.RELEASED,
        )

        self._lease_lookup[lease_id] = released_lease
        if self._active_leases.get(lease.profile_name) and self._active_leases[lease.profile_name].lease_id == lease_id:
            del self._active_leases[lease.profile_name]

        logger.info("Released browser profile lease %s on '%s'", lease_id, lease.profile_name)
        return released_lease

    def get_active_lease(self, profile_name: str) -> BrowserProfileLease | None:
        """Query currently active lease on a browser profile, accounting for TTL expiration."""
        lease = self._active_leases.get(profile_name)
        if lease is None:
            return None

        if time.time() >= lease.acquired_at + lease.ttl_seconds:
            self._expire_lease(lease)
            return None

        return lease

    def list_active_leases(self) -> list[BrowserProfileLease]:
        """List all currently valid non-expired leases."""
        now = time.time()
        valid: list[BrowserProfileLease] = []
        expired_profiles: list[BrowserProfileLease] = []

        for lease in self._active_leases.values():
            if now >= lease.acquired_at + lease.ttl_seconds:
                expired_profiles.append(lease)
            else:
                valid.append(lease)

        for exp in expired_profiles:
            self._expire_lease(exp)

        return valid

    def _expire_lease(self, lease: BrowserProfileLease) -> None:
        expired = BrowserProfileLease(
            lease_id=lease.lease_id,
            profile_name=lease.profile_name,
            consumer_id=lease.consumer_id,
            acquired_at=lease.acquired_at,
            ttl_seconds=lease.ttl_seconds,
            status=BrowserLeaseStatus.EXPIRED,
        )
        self._lease_lookup[lease.lease_id] = expired
        if lease.profile_name in self._active_leases and self._active_leases[lease.profile_name].lease_id == lease.lease_id:
            del self._active_leases[lease.profile_name]
