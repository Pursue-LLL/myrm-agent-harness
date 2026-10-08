"""Identity and scope evaluator for streaming endpoint gate parity.

[INPUT]
- StreamingEndpointContract, StreamingClientIdentity, requested resource ID.

[OUTPUT]
- StreamingGateVerdict, StreamingParityAuditIssue list.

[POS]
- Harness core security engine. Enforces zero bypass on SSE and WebSocket connections,
  ensuring they require strict identity and resource scope parity with REST APIs.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from myrm_agent_harness.core.security.streaming_gate.registry import (
    StreamingEndpointRegistry,
)
from myrm_agent_harness.core.security.streaming_gate.types import (
    GateDecision,
    StreamingAccessDeniedError,
    StreamingClientIdentity,
    StreamingEndpointContract,
    StreamingGateVerdict,
    StreamingParityAuditIssue,
)

logger = logging.getLogger(__name__)


class StreamingIdentityGateEvaluator:
    """Evaluates whether streaming connection attempts comply with declared security gates."""

    def __init__(self, registry: StreamingEndpointRegistry | None = None) -> None:
        self._registry = registry or StreamingEndpointRegistry()

    @property
    def registry(self) -> StreamingEndpointRegistry:
        """Underlying endpoint contract registry."""
        return self._registry

    def evaluate_access(
        self,
        contract: StreamingEndpointContract,
        identity: StreamingClientIdentity,
        requested_resource_id: str | None = None,
    ) -> StreamingGateVerdict:
        """Evaluate client identity against endpoint contract to decide access."""
        # 1. Check authentication requirement
        if contract.requires_auth and not identity.subject_id:
            return StreamingGateVerdict(
                decision=GateDecision.DENIED_UNAUTHENTICATED,
                endpoint_path=contract.endpoint_path,
                reason="Authentication required: Anonymous or missing credentials on streaming route.",
                status_code=401,
            )

        # 2. Check remote exposure restriction
        if identity.is_remote and not contract.supports_remote_access:
            return StreamingGateVerdict(
                decision=GateDecision.DENIED_REMOTE_BLOCKED,
                endpoint_path=contract.endpoint_path,
                reason="Access Denied: Endpoint is restricted to local-only connections.",
                status_code=403,
            )

        # 3. Check scope requirement
        if contract.required_scope and contract.required_scope not in identity.granted_scopes:
            return StreamingGateVerdict(
                decision=GateDecision.DENIED_SCOPE_MISMATCH,
                endpoint_path=contract.endpoint_path,
                reason=f"Access Denied: Missing required permission scope '{contract.required_scope}'.",
                status_code=403,
            )

        # 4. Check resource-level binding confinement
        # If client identity is constrained to specific resource IDs (e.g. mobile pair token bound to chat_id)
        if (
            identity.bound_resource_ids
            and requested_resource_id
            and requested_resource_id not in identity.bound_resource_ids
        ):
            return StreamingGateVerdict(
                    decision=GateDecision.DENIED_RESOURCE_UNBOUND,
                    endpoint_path=contract.endpoint_path,
                    reason=(
                        f"Scope Confinement Denied: Client token is restricted to resources "
                        f"{identity.bound_resource_ids}, but requested '{requested_resource_id}'."
                    ),
                    status_code=403,
                )

        return StreamingGateVerdict(
            decision=GateDecision.ALLOWED,
            endpoint_path=contract.endpoint_path,
            reason="Access Granted: Identity and scope verified.",
            status_code=200,
        )

    def assert_access(
        self,
        contract: StreamingEndpointContract,
        identity: StreamingClientIdentity,
        requested_resource_id: str | None = None,
    ) -> None:
        """Assert access permission, raising StreamingAccessDeniedError on non-200 outcome."""
        verdict = self.evaluate_access(contract, identity, requested_resource_id)
        if verdict.decision != GateDecision.ALLOWED:
            raise StreamingAccessDeniedError(
                f"[{verdict.status_code}] Streaming access denied for '{contract.endpoint_path}': {verdict.reason}"
            )

    @staticmethod
    def audit_parity(
        contracts: Sequence[StreamingEndpointContract],
    ) -> tuple[StreamingParityAuditIssue, ...]:
        """Perform systematic audit on streaming route contracts to detect security blindspots."""
        issues: list[StreamingParityAuditIssue] = []

        for c in contracts:
            # 1. Unauthenticated streaming route
            if not c.requires_auth:
                issues.append(
                    StreamingParityAuditIssue(
                        endpoint_path=c.endpoint_path,
                        transport=c.transport,
                        issue_type="UNAUTHENTICATED_STREAM",
                        description=f"Streaming route '{c.endpoint_path}' allows unauthenticated access.",
                        severity="CRITICAL",
                    )
                )

            # 2. Resource-targeted stream lacking scope definition
            if c.target_resource_type and not c.required_scope:
                issues.append(
                    StreamingParityAuditIssue(
                        endpoint_path=c.endpoint_path,
                        transport=c.transport,
                        issue_type="UNSCOPED_RESOURCE_STREAM",
                        description=(
                            f"Streaming route '{c.endpoint_path}' targets resource '{c.target_resource_type}' "
                            f"without an explicit required scope."
                        ),
                        severity="HIGH",
                    )
                )

        return tuple(issues)
