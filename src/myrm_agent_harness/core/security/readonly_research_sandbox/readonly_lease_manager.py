"""
[POS] src/myrm_agent_harness/core/security/readonly_research_sandbox/readonly_lease_manager.py
[INPUT] threading, time, uuid, typing, .types (LeaseStatusEnum, ReadOnlyLeaseRecord, ResearchModeEnum)
[OUTPUT] ReadOnlyLeaseManager

Manages dynamic read-only authority leases for autonomous research sessions,
physically stripping write/side-effect capabilities and strictly confining tool dispatch.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading
import time
import uuid

from .types import LeaseStatusEnum, ReadOnlyLeaseRecord, ResearchModeEnum


class ReadOnlyLeaseManager:
    """Coordinates lifecycle and strict tool boundary enforcement of read-only research leases."""

    def __init__(self, default_ttl_seconds: float = 3600.0) -> None:
        self._lock = threading.RLock()
        self._default_ttl = default_ttl_seconds
        self._leases: dict[str, ReadOnlyLeaseRecord] = {}  # session_id -> lease

    def grant_lease(
        self,
        session_id: str,
        research_mode: ResearchModeEnum = ResearchModeEnum.AUTONOMOUS_RESEARCH,
        ttl_seconds: float | None = None,
        custom_allowed_tools: tuple[str, ...] | None = None,
    ) -> ReadOnlyLeaseRecord:
        """Grant a dynamic read-only research lease to an execution session."""
        now = time.time()
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        lid = f"lease-{uuid.uuid4().hex[:12]}"

        allowed = custom_allowed_tools if custom_allowed_tools is not None else (
            "read_file",
            "web_search",
            "read_web_page",
            "fetch_doc",
            "grep_search",
            "list_dir",
            "view_image",
        )

        lease = ReadOnlyLeaseRecord(
            lease_id=lid,
            session_id=session_id,
            research_mode=research_mode,
            granted_at=now,
            expires_at=now + ttl,
            status=LeaseStatusEnum.ACTIVE,
            allowed_tools=allowed,
        )

        with self._lock:
            self._leases[session_id] = lease

        return lease

    def get_lease(
        self, session_id: str, current_time: float | None = None
    ) -> ReadOnlyLeaseRecord | None:
        """Retrieve lease for session, lazily evaluating expiration."""
        now = current_time if current_time is not None else time.time()
        with self._lock:
            lease = self._leases.get(session_id)
            if lease is None:
                return None

            if lease.status == LeaseStatusEnum.ACTIVE and now > lease.expires_at:
                lease = ReadOnlyLeaseRecord(
                    lease_id=lease.lease_id,
                    session_id=lease.session_id,
                    research_mode=lease.research_mode,
                    granted_at=lease.granted_at,
                    expires_at=lease.expires_at,
                    status=LeaseStatusEnum.EXPIRED,
                    allowed_tools=lease.allowed_tools,
                    blocked_side_effects=lease.blocked_side_effects,
                )
                self._leases[session_id] = lease

            return lease

    def revoke_lease(self, session_id: str) -> ReadOnlyLeaseRecord | None:
        """Revoke active read-only lease immediately."""
        with self._lock:
            lease = self._leases.get(session_id)
            if lease is None:
                return None

            if lease.status == LeaseStatusEnum.ACTIVE:
                lease = ReadOnlyLeaseRecord(
                    lease_id=lease.lease_id,
                    session_id=lease.session_id,
                    research_mode=lease.research_mode,
                    granted_at=lease.granted_at,
                    expires_at=lease.expires_at,
                    status=LeaseStatusEnum.REVOKED,
                    allowed_tools=lease.allowed_tools,
                    blocked_side_effects=lease.blocked_side_effects,
                )
                self._leases[session_id] = lease

            return lease

    def evaluate_tool(self, session_id: str, tool_name: str) -> tuple[bool, str]:
        """Evaluate if tool can run or is physically stripped by active read-only lease.

        Returns:
            Tuple of (is_allowed, explanation)
        """
        lease = self.get_lease(session_id)
        if lease is None or lease.status != LeaseStatusEnum.ACTIVE:
            return True, "No active read-only lease; standard dispatch permitted."

        if tool_name in lease.allowed_tools:
            return True, f"Tool '{tool_name}' permitted under active read-only research lease."

        if tool_name in lease.blocked_side_effects:
            return (
                False,
                (
                    f"Tool '{tool_name}' physically stripped by Read-Only Research Lease. "
                    "All destructive side-effects are disabled during autonomous exploration."
                ),
            )

        return (
            False,
            (
                f"Tool '{tool_name}' is not in the safe read-only whitelist of active lease "
                f"'{lease.lease_id}'. Execution blocked."
            ),
        )
