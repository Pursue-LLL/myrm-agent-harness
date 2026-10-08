"""Decoupled read/write dynamic mount router for multi-agent Memory Cubes.

[INPUT]
- threading (RLock)
- .cube_store::MemoryCubeStore
- .models::{CubeQueryRequest, CubeQueryResult, CubeWriteRequest, CubeWriteResult, MountPolicy}

[OUTPUT]
- DynamicMountRouter: Enforces read/write separation and federated multi-cube dispatching.

[POS]
Routing and authorization gate for Item 124 (MemoryCubeScopedIsolationAndDynamicMountingSuite).
"""

from __future__ import annotations

import logging
from threading import RLock

from myrm_agent_harness.toolkits.memory.mem_cube.cube_store import MemoryCubeStore
from myrm_agent_harness.toolkits.memory.mem_cube.models import (
    CubeQueryRequest,
    CubeQueryResult,
    CubeWriteRequest,
    CubeWriteResult,
    MountPolicy,
)

logger = logging.getLogger(__name__)


class DynamicMountRouter:
    """Routes read queries and write mutations across mounted Memory Cubes with strict RBAC."""

    def __init__(self, default_global_cube_id: str = "cube-global-shared") -> None:
        self._lock = RLock()
        self._policies: dict[str, MountPolicy] = {}
        self._default_global_cube_id = default_global_cube_id

    def register_policy(self, policy: MountPolicy) -> MountPolicy:
        """Register or update mount topology for an agent."""
        with self._lock:
            self._policies[policy.agent_id] = policy
            logger.info(
                "Registered MountPolicy for agent %s: %d readable, %d writable",
                policy.agent_id,
                len(policy.readable_cube_ids),
                len(policy.writable_cube_ids),
            )
            return policy

    def get_policy(self, agent_id: str) -> MountPolicy | None:
        """Retrieve active mount policy for an agent."""
        with self._lock:
            return self._policies.get(agent_id)

    def list_policies(self) -> list[MountPolicy]:
        """List all active agent mount policies."""
        with self._lock:
            return list(self._policies.values())

    def resolve_readable_cubes(
        self,
        agent_id: str | None,
        explicit_cube_ids: list[str] | None = None,
    ) -> list[str]:
        """Determine authorized target cubes for a read operation."""
        with self._lock:
            if explicit_cube_ids:
                if agent_id and agent_id in self._policies:
                    policy = self._policies[agent_id]
                    # Filter explicit targets to permitted readable subset
                    allowed = [c for c in explicit_cube_ids if c in policy.readable_cube_ids]
                    return allowed or [self._default_global_cube_id]
                return explicit_cube_ids

            if agent_id and agent_id in self._policies:
                policy = self._policies[agent_id]
                return list(policy.readable_cube_ids) or [self._default_global_cube_id]

            return [self._default_global_cube_id]

    def resolve_writable_cube(
        self,
        agent_id: str | None,
        target_cube_id: str | None = None,
    ) -> str:
        """Resolve and authorize target cube for a mutation, preventing cross-tenant leakage."""
        with self._lock:
            if not agent_id:
                # Standalone operation
                if not target_cube_id:
                    return self._default_global_cube_id
                return target_cube_id

            policy = self._policies.get(agent_id)
            if not policy:
                # Default policy: allowed to write to global or explicit target
                return target_cube_id or self._default_global_cube_id

            dest_cube = target_cube_id or policy.default_write_cube_id or self._default_global_cube_id

            if policy.strict_isolation and dest_cube not in policy.writable_cube_ids:
                raise PermissionError(
                    f"Agent '{agent_id}' is not authorized to write to MemoryCube '{dest_cube}'. "
                    f"Permitted writable cubes: {policy.writable_cube_ids}"
                )

            return dest_cube

    def read_federated(
        self,
        store: MemoryCubeStore,
        request: CubeQueryRequest,
    ) -> CubeQueryResult:
        """Execute federated query across authorized mounted cubes."""
        target_cubes = self.resolve_readable_cubes(
            agent_id=request.agent_id,
            explicit_cube_ids=request.explicit_cube_ids,
        )

        records_by_cube: dict[str, list] = {}
        total_found = 0

        for cid in target_cubes:
            records = store.query_records(
                cube_id=cid,
                query=request.query,
                limit=request.limit_per_cube,
            )
            if records:
                records_by_cube[cid] = records
                total_found += len(records)

        return CubeQueryResult(
            query=request.query,
            records_by_cube=records_by_cube,
            total_found=total_found,
            audited_cube_ids=target_cubes,
        )

    def write_routed(
        self,
        store: MemoryCubeStore,
        request: CubeWriteRequest,
    ) -> CubeWriteResult:
        """Deposit memory into strictly authorized target cube."""
        try:
            target_cube = self.resolve_writable_cube(
                agent_id=request.agent_id,
                target_cube_id=request.target_cube_id,
            )
            record = store.store_record(
                cube_id=target_cube,
                content=request.content,
                importance=request.importance,
                metadata=request.metadata,
            )
            return CubeWriteResult(
                success=True,
                record=record,
                target_cube_id=target_cube,
                rejection_reason=None,
            )
        except (PermissionError, ValueError, KeyError) as err:
            logger.warning(
                "Write rejected for agent %s -> %s: %s",
                request.agent_id,
                request.target_cube_id,
                err,
            )
            return CubeWriteResult(
                success=False,
                record=None,
                target_cube_id=request.target_cube_id or "unknown",
                rejection_reason=str(err),
            )
