"""Cross-client memory leakage firewall and partition isolation guard.

[INPUT]
- logging
- myrm_agent_harness.toolkits.memory.types::{MemoryScope, MemorySearchResult}
- myrm_agent_harness.toolkits.memory.client_partition.types::{
      CrossClientLeakViolation,
      PartitionInspectionReport,
  }

[OUTPUT]
- CrossClientLeakGuard: Interceptor screening retrieval results and write requests against client cross-pollution

[POS]
Defensive screening engine enforcing strictly segregated boundaries between client accounts.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.memory.client_partition.types import (
    CrossClientLeakViolation,
    PartitionInspectionReport,
)
from myrm_agent_harness.toolkits.memory.types import MemoryScope, MemorySearchResult

logger = logging.getLogger(__name__)


class CrossClientLeakGuard:
    """Detects and suppresses memories originating from foreign client scopes."""

    def __init__(self, *, default_allow_global: bool = True) -> None:
        self._default_allow_global = default_allow_global

    def is_foreign_memory(
        self,
        scope: MemoryScope,
        active_client_id: str,
        *,
        allow_global: bool | None = None,
    ) -> tuple[bool, str | None, str | None]:
        """Determine whether a memory item belongs to another client.

        Returns:
            (is_leak, offending_client_id, reason)
        """
        allow_shared_global = (
            allow_global if allow_global is not None else self._default_allow_global
        )

        # 1. Explicit client_id ownership check
        if scope.client_id is not None:
            if scope.client_id != active_client_id:
                return (
                    True,
                    scope.client_id,
                    f"Memory explicitly tagged with foreign client_id '{scope.client_id}'",
                )
            return False, None, None

        # 2. Namespace prefix scan for foreign client:* tokens
        client_tag = f"client:{active_client_id}"
        all_namespaces = [scope.primary_namespace, *scope.namespaces]

        foreign_client_namespaces: list[str] = []
        for ns in all_namespaces:
            if ns.startswith("client:") and ns != client_tag:
                foreign_client_namespaces.append(ns)

        if foreign_client_namespaces:
            offending_ns = foreign_client_namespaces[0]
            foreign_id = offending_ns.removeprefix("client:")
            return (
                True,
                foreign_id,
                f"Memory namespace '{offending_ns}' belongs to a different client partition",
            )

        # 3. Pure global/agent broadcast check
        if not allow_shared_global and scope.primary_namespace == "global":
            return (
                True,
                None,
                "Global shared memory disallowed by strict client partition policy",
            )

        return False, None, None

    def validate_write_scope(
        self,
        scope: MemoryScope,
        target_client_id: str,
    ) -> None:
        """Validate that a write operation is strictly confined to target client."""
        is_leak, offending_id, reason = self.is_foreign_memory(
            scope, target_client_id, allow_global=True
        )
        if is_leak:
            raise ValueError(
                f"Cross-client memory write rejected for client '{target_client_id}': "
                f"{reason} (offending client: {offending_id})"
            )

    def screen_search_results(
        self,
        results: list[MemorySearchResult],
        active_client_id: str,
        *,
        allow_global: bool | None = None,
    ) -> tuple[list[MemorySearchResult], PartitionInspectionReport]:
        """Screen retrieval candidates and purge any item belonging to another client."""
        safe_results: list[MemorySearchResult] = []
        violations: list[CrossClientLeakViolation] = []

        for candidate in results:
            is_leak, offending_id, reason = self.is_foreign_memory(
                candidate.memory.scope,
                active_client_id,
                allow_global=allow_global,
            )
            if is_leak:
                logger.warning(
                    "Intercepted cross-client memory leakage for client '%s': %s",
                    active_client_id,
                    reason,
                )
                violations.append(
                    CrossClientLeakViolation(
                        target_client_id=active_client_id,
                        offending_client_id=offending_id,
                        offending_namespace=candidate.memory.scope.primary_namespace,
                        memory_id=candidate.memory.id,
                        reason=reason or "Foreign client partition boundary violation",
                    )
                )
            else:
                safe_results.append(candidate)

        report = PartitionInspectionReport(
            target_client_id=active_client_id,
            total_evaluated=len(results),
            allowed_count=len(safe_results),
            filtered_count=len(violations),
            violations=violations,
        )
        return safe_results, report
