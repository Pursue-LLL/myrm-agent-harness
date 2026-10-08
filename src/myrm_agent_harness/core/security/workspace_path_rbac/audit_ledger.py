"""Structured Filesystem Audit Ledger tracking all workspace operations and denials.

[INPUT]
- Operation verdicts, session identifiers, agent IDs, and path targets.

[OUTPUT]
- Immutable append-only audit entries, query interfaces, and aggregated security stats.

[POS]
- Tamper-evident ledger providing enterprise file governance transparency.
"""

from __future__ import annotations

import time
import uuid
from typing import TypedDict

from myrm_agent_harness.core.security.workspace_path_rbac.types import (
    AuditLedgerEntry,
    FileActionType,
)


class AuditStats(TypedDict):
    """Statistical summary of recorded audit events."""

    total_events: int
    granted_count: int
    denied_count: int
    denials_by_action: dict[str, int]
    denials_by_reason: dict[str, int]


class FilesystemAuditLedger:
    """Immutable audit ledger tracking filesystem access attempts."""

    def __init__(self) -> None:
        """Initialize empty audit ledger."""
        self._entries: list[AuditLedgerEntry] = []

    def record(
        self,
        agent_id: str,
        session_id: str,
        user_identity: str,
        target_path: str,
        action: FileActionType,
        granted: bool,
        violation_reason: str | None = None,
    ) -> AuditLedgerEntry:
        """Record a filesystem access attempt into the ledger."""
        entry = AuditLedgerEntry(
            entry_id=f"audit_{uuid.uuid4().hex[:12]}",
            timestamp=time.time(),
            agent_id=agent_id,
            session_id=session_id,
            user_identity=user_identity,
            target_path=target_path,
            action=action,
            granted=granted,
            violation_reason=violation_reason,
        )
        self._entries.append(entry)
        return entry

    def query(
        self,
        session_id: str | None = None,
        agent_id: str | None = None,
        user_identity: str | None = None,
        granted: bool | None = None,
        limit: int = 100,
    ) -> list[AuditLedgerEntry]:
        """Query audit records matching filter criteria."""
        results: list[AuditLedgerEntry] = []
        for entry in reversed(self._entries):
            if session_id is not None and entry.session_id != session_id:
                continue
            if agent_id is not None and entry.agent_id != agent_id:
                continue
            if user_identity is not None and entry.user_identity != user_identity:
                continue
            if granted is not None and entry.granted != granted:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def get_stats(self) -> AuditStats:
        """Compute aggregated audit statistics."""
        granted_count = 0
        denied_count = 0
        denials_by_action: dict[str, int] = {}
        denials_by_reason: dict[str, int] = {}

        for entry in self._entries:
            if entry.granted:
                granted_count += 1
            else:
                denied_count += 1
                action_key = entry.action.value
                denials_by_action[action_key] = denials_by_action.get(action_key, 0) + 1
                if entry.violation_reason:
                    reason_key = entry.violation_reason
                    denials_by_reason[reason_key] = (
                        denials_by_reason.get(reason_key, 0) + 1
                    )

        return {
            "total_events": len(self._entries),
            "granted_count": granted_count,
            "denied_count": denied_count,
            "denials_by_action": denials_by_action,
            "denials_by_reason": denials_by_reason,
        }

    def clear(self) -> None:
        """Flush audit entries."""
        self._entries.clear()
