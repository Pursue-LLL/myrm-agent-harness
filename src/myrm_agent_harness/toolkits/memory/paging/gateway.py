"""Hard Boundary Scope Gateway enforcing physical multi-tenant and project isolation.

[INPUT]
- toolkits.memory.paging.models::AccessViolationAudit, AccessViolationError, HardScopeContext,
  MemoryPageQuery (POS: Data models for Agent-Driven Memory Paging and Hard Boundary Governance Engine.)

[OUTPUT]
- HardBoundaryScopeGateway: Application-layer security gateway preventing cross-tenant or cross-project
  memory probing.

[POS]
Hard Boundary Scope Gateway enforcing physical multi-tenant and project isolation.
"""

import uuid
from datetime import UTC, datetime

from .models import (
    AccessViolationAudit,
    AccessViolationError,
    HardScopeContext,
    MemoryPageQuery,
)


class HardBoundaryScopeGateway:
    """Application-layer security gateway preventing cross-tenant or cross-project memory probing."""

    def __init__(self) -> None:
        """Initialize gateway with in-memory audit log store."""
        self._audit_log: list[AccessViolationAudit] = []

    @property
    def audit_logs(self) -> list[AccessViolationAudit]:
        """Return historical security violation audit entries."""
        return list(self._audit_log)

    def validate_and_enforce_scope(
        self,
        query: MemoryPageQuery,
        context: HardScopeContext,
        custom_now: datetime | None = None,
    ) -> HardScopeContext:
        """Inspect the incoming page query and enforce that query bounds strictly match the context.

        Args:
            query: The agent's pagination query request.
            context: The authenticated application-layer physical scope.
            custom_now: Optional deterministic timestamp for audit logs.

        Returns:
            The authoritative HardScopeContext for downstream data isolation.

        Raises:
            AccessViolationError: If query explicitly purports a mismatched project boundary.
        """
        now = custom_now or datetime.now(UTC)

        # Intercept attempted forging of project_id
        if query.purported_project_id is not None:
            claimed = query.purported_project_id.strip()
            actual = context.project_id.strip()
            if claimed != actual:
                audit = AccessViolationAudit(
                    violation_id=f"audit-{uuid.uuid4().hex[:12]}",
                    session_id=context.session_id,
                    attempted_scope=f"project:{claimed}",
                    actual_scope=f"project:{actual}",
                    timestamp=now,
                    details=(
                        f"Agent in session '{context.session_id}' attempted to probe "
                        f"project '{claimed}', but hard boundary enforces '{actual}'."
                    ),
                )
                self._audit_log.append(audit)
                raise AccessViolationError(
                    f"Access Denied: Attempted to query project '{claimed}' outside "
                    f"authorized physical scope '{actual}'."
                )

        # Enforce that query downstream is strictly bound to context
        return context

    def clear_audit_logs(self) -> None:
        """Clear audit history (typically used between test fixtures)."""
        self._audit_log.clear()
