"""Composite Guard orchestrating Workspace Path RBAC and Audit Ledger.

[INPUT]
- Policy configurations, attempted file actions, session IDs, and enterprise identity context.

[OUTPUT]
- Verified permission verdicts, automatic write denials with UI cards, and tamper-evident audit records.

[POS]
- Main architectural boundary for workspace path segregation and triple write defense.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.workspace_path_rbac.audit_ledger import (
    AuditStats,
    FilesystemAuditLedger,
)
from myrm_agent_harness.core.security.workspace_path_rbac.policy_engine import (
    WorkspacePathPolicyEngine,
)
from myrm_agent_harness.core.security.workspace_path_rbac.types import (
    AccessCheckVerdict,
    AuditLedgerEntry,
    FileActionType,
    WorkspacePolicy,
)


class GranularWorkspacePathGuard:
    """Zero-trust guard enforcing filesystem RBAC segregation and triple write defenses."""

    def __init__(
        self,
        audit_ledger: FilesystemAuditLedger | None = None,
    ) -> None:
        """Initialize guard with audit ledger and policy store."""
        self._ledger = audit_ledger or FilesystemAuditLedger()
        self._policies: dict[str, WorkspacePolicy] = {}

    def register_policy(self, policy: WorkspacePolicy) -> None:
        """Register or update a workspace RBAC policy."""
        self._policies[policy.policy_id] = policy

    def get_policy(self, policy_id: str) -> WorkspacePolicy | None:
        """Retrieve policy by identifier."""
        return self._policies.get(policy_id)

    def check_access_and_audit(
        self,
        policy_id: str,
        agent_id: str,
        session_id: str,
        user_identity: str,
        relative_path: str,
        action: FileActionType,
    ) -> AccessCheckVerdict:
        """Evaluate access against workspace policy and record entry into the audit ledger."""
        policy = self._policies.get(policy_id)
        if policy is None:
            # Safe default fallback: default closed policy
            policy = WorkspacePolicy(
                policy_id=policy_id,
                user_identity=user_identity,
                project_root=".",
                rules=[],
                allowed_deliverables_dir="deliverables",
            )

        # 1. Policy evaluation
        verdict = WorkspacePathPolicyEngine.evaluate(
            policy=policy,
            relative_path=relative_path,
            action=action,
        )

        # 2. Record in audit ledger
        self._ledger.record(
            agent_id=agent_id,
            session_id=session_id,
            user_identity=user_identity,
            target_path=relative_path,
            action=action,
            granted=verdict.allowed,
            violation_reason=verdict.violation_reason,
        )

        return verdict

    def query_audit_ledger(
        self,
        session_id: str | None = None,
        agent_id: str | None = None,
        user_identity: str | None = None,
        granted: bool | None = None,
        limit: int = 100,
    ) -> list[AuditLedgerEntry]:
        """Query entries from the audit ledger."""
        return self._ledger.query(
            session_id=session_id,
            agent_id=agent_id,
            user_identity=user_identity,
            granted=granted,
            limit=limit,
        )

    def get_audit_stats(self) -> AuditStats:
        """Retrieve audit ledger statistics."""
        return self._ledger.get_stats()
