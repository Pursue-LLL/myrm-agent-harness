"""
[POS] src/myrm_agent_harness/core/security/event_capability_attenuation/attenuation_capsule.py
[INPUT] threading, typing, .types (AttenuationRule, EventTrustScopeEnum, TicketRiskLevelEnum)
[OUTPUT] CapabilityAttenuationCapsule

Enforces execution capability attenuation on agents awakened by untrusted external events,
stripping destructive/irreversible write tools and confining execution to read-only safe operations.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading

from .types import AttenuationRule, EventTrustScopeEnum, TicketRiskLevelEnum


class CapabilityAttenuationCapsule:
    """Enforces capability attenuation and tool access boundaries based on event origin trust."""

    def __init__(self, rule: AttenuationRule | None = None) -> None:
        self._lock = threading.Lock()
        self._rule = rule or AttenuationRule()
        self._session_scopes: dict[str, EventTrustScopeEnum] = {}

    def set_session_scope(self, session_id: str, scope: EventTrustScopeEnum) -> None:
        """Bind session execution context to a trust scope."""
        with self._lock:
            self._session_scopes[session_id] = scope

    def get_session_scope(self, session_id: str) -> EventTrustScopeEnum:
        """Get active trust scope for a session, defaulting to USER_INTERACTIVE."""
        with self._lock:
            return self._session_scopes.get(session_id, EventTrustScopeEnum.USER_INTERACTIVE)

    def remove_session(self, session_id: str) -> None:
        """Clean up session trust scope."""
        with self._lock:
            self._session_scopes.pop(session_id, None)

    def evaluate_tool_access(
        self, session_id: str, tool_name: str
    ) -> tuple[bool, str, TicketRiskLevelEnum]:
        """Evaluate whether tool invocation is permissible or requires out-of-band human approval.

        Returns:
            Tuple of (is_allowed, explanation, risk_level)
        """
        scope = self.get_session_scope(session_id)

        # 1. Interactive direct human session: full capabilities
        if scope == EventTrustScopeEnum.USER_INTERACTIVE:
            return True, "User interactive session allows direct execution.", TicketRiskLevelEnum.LOW

        # 2. Complete Quarantine mode
        if scope == EventTrustScopeEnum.ISOLATED_QUARANTINE:
            if tool_name in self._rule.read_only_allowed_tools:
                return True, "Quarantined session allows safe read-only tool.", TicketRiskLevelEnum.LOW
            return (
                False,
                f"Quarantine isolation blocked tool '{tool_name}'.",
                TicketRiskLevelEnum.CRITICAL,
            )

        # 3. LOW_TRUST_EVENT_SCOPE: Automated unattended event wakeup
        if tool_name in self._rule.read_only_allowed_tools:
            return (
                True,
                f"Tool '{tool_name}' matches event-safe read-only whitelist.",
                TicketRiskLevelEnum.LOW,
            )

        if tool_name in self._rule.blocked_tools:
            risk = (
                TicketRiskLevelEnum.CRITICAL
                if tool_name in ("rm_rf", "drop_database", "deploy_production")
                else TicketRiskLevelEnum.HIGH
            )
            return (
                False,
                (
                    f"Irreversible tool '{tool_name}' attenuated under external event scope. "
                    "Asynchronous out-of-band approval ticket required."
                ),
                risk,
            )

        # Uncategorized write/modify action: medium risk approval required
        return (
            False,
            f"Mutating tool '{tool_name}' under event scope requires async human sign-off.",
            TicketRiskLevelEnum.MEDIUM,
        )
