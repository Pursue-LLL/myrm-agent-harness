"""Privilege Intersection Guard for blocking privilege amplification attacks.

[INPUT]
- agent.security.delegation.models::TriadDelegationToken (POS: Immutable tokens capturing InitialRequester,
  ExecutorAgent, and BusinessApprover with strict intersection-based privilege calculation to prevent
  amplification attacks.)

[OUTPUT]
- PrivilegeAmplificationBlockedError: Raised when an operation is blocked due to lack of effective
  intersection scopes.
- PrivilegeIntersectionGuard: Security guard verifying that the triad delegation token satisfies required
  scopes.

[POS]
Enforces that governed actions strictly require effective intersection privileges between InitialRequester
and ExecutorAgent. Prevents low-privilege actors from borrowing high-privilege agent service accounts.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.agent.security.delegation.models import TriadDelegationToken

logger = logging.getLogger(__name__)


class PrivilegeAmplificationBlockedError(Exception):
    """Raised when an operation is blocked due to lack of effective intersection scopes."""

    def __init__(
        self,
        message: str,
        required_scope: str,
        initial_requester_id: str,
        executor_agent_id: str,
        effective_scopes: frozenset[str],
    ) -> None:
        super().__init__(message)
        self.required_scope = required_scope
        self.initial_requester_id = initial_requester_id
        self.executor_agent_id = executor_agent_id
        self.effective_scopes = effective_scopes

    def to_diagnostic_info(self) -> dict[str, object]:
        """Convert failure details to machine-readable diagnostic info."""
        return {
            "privilege_amplification_blocked": True,
            "required_scope": self.required_scope,
            "initial_requester_id": self.initial_requester_id,
            "executor_agent_id": self.executor_agent_id,
            "effective_scopes": list(self.effective_scopes),
        }


class PrivilegeIntersectionGuard:
    """Security guard verifying that the triad delegation token satisfies required scopes."""

    @classmethod
    def assert_scope_allowed(
        cls,
        token: TriadDelegationToken | None,
        required_scope: str,
        action_name: str = "",
    ) -> None:
        """Assert that the required scope is present in the token's effective privilege intersection.

        Raises:
            PrivilegeAmplificationBlockedError: If the token is missing or lacks the required scope.
        """
        if token is None:
            # When no delegation token is attached, fail-close for governed actions
            logger.warning(
                "Privilege amplification gate blocked: Missing TriadDelegationToken for action '%s' requiring '%s'",
                action_name,
                required_scope,
            )
            raise PrivilegeAmplificationBlockedError(
                message=f"Action '{action_name}' requires scope '{required_scope}', but no delegation context exists.",
                required_scope=required_scope,
                initial_requester_id="anonymous",
                executor_agent_id="unknown",
                effective_scopes=frozenset(),
            )

        if token.is_expired:
            logger.warning(
                "Privilege amplification gate blocked: Expired token for requester '%s'",
                token.initial_requester.subject_id,
            )
            raise PrivilegeAmplificationBlockedError(
                message=f"Delegation token expired for requester '{token.initial_requester.subject_id}'.",
                required_scope=required_scope,
                initial_requester_id=token.initial_requester.subject_id,
                executor_agent_id=token.executor_agent.subject_id,
                effective_scopes=token.effective_scopes,
            )

        if not token.has_scope(required_scope):
            logger.warning(
                "Privilege amplification gate blocked: Requester '%s' lacks scope '%s' through agent '%s'",
                token.initial_requester.subject_id,
                required_scope,
                token.executor_agent.subject_id,
            )
            raise PrivilegeAmplificationBlockedError(
                message=(
                    f"Privilege amplification blocked: Initial requester '{token.initial_requester.subject_id}' "
                    f"lacks scope '{required_scope}' (effective: {sorted(token.effective_scopes)})."
                ),
                required_scope=required_scope,
                initial_requester_id=token.initial_requester.subject_id,
                executor_agent_id=token.executor_agent.subject_id,
                effective_scopes=token.effective_scopes,
            )

    @classmethod
    def is_scope_allowed(cls, token: TriadDelegationToken | None, required_scope: str) -> bool:
        """Pure boolean check whether the required scope is granted in the delegation token."""
        if token is None or token.is_expired:
            return False
        return token.has_scope(required_scope)
