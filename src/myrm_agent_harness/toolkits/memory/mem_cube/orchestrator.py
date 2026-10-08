"""Unified facade orchestrator for Memory Cube Scoped Isolation & Dynamic Mounting Suite.

[INPUT]
- logging
- .cube_store::MemoryCubeStore
- .models::{CubeMemoryRecord, CubeQueryRequest, CubeQueryResult, CubeScopeType, CubeWriteRequest, CubeWriteResult, MemoryCube, MountPolicy}
- .mount_router::DynamicMountRouter

[OUTPUT]
- MemoryCubeOrchestrator: High-level orchestration facade managing cubes, policies, and routed recall.

[POS]
Central entry facade for Item 124 (MemoryCubeScopedIsolationAndDynamicMountingSuite).
"""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.memory.mem_cube.cube_store import MemoryCubeStore
from myrm_agent_harness.toolkits.memory.mem_cube.models import (
    CubeMemoryRecord,
    CubeQueryRequest,
    CubeQueryResult,
    CubeScopeType,
    CubeWriteRequest,
    CubeWriteResult,
    MemoryCube,
    MountPolicy,
)
from myrm_agent_harness.toolkits.memory.mem_cube.mount_router import DynamicMountRouter

logger = logging.getLogger(__name__)


class MemoryCubeOrchestrator:
    """Orchestrates MemoryCube lifecycle, multi-agent mount policies, and read/write separation."""

    def __init__(
        self,
        store: MemoryCubeStore | None = None,
        router: DynamicMountRouter | None = None,
    ) -> None:
        self._store = store or MemoryCubeStore()
        self._router = router or DynamicMountRouter()

    @property
    def store(self) -> MemoryCubeStore:
        """Access underlying cube store."""
        return self._store

    @property
    def router(self) -> DynamicMountRouter:
        """Access underlying mount router."""
        return self._router

    def create_cube(
        self,
        name: str,
        scope_type: CubeScopeType,
        owner_id: str | None = None,
        description: str = "",
        is_read_only: bool = False,
        tags: list[str] | None = None,
        cube_id: str | None = None,
    ) -> MemoryCube:
        """Create a new MemoryCube compartment."""
        return self._store.create_cube(
            name=name,
            scope_type=scope_type,
            owner_id=owner_id,
            description=description,
            is_read_only=is_read_only,
            tags=tags,
            cube_id=cube_id,
        )

    def get_cube(self, cube_id: str) -> MemoryCube | None:
        """Retrieve a specific cube by ID."""
        return self._store.get_cube(cube_id)

    def list_cubes(
        self,
        scope_type: CubeScopeType | None = None,
        owner_id: str | None = None,
    ) -> list[MemoryCube]:
        """List cubes matching optional scope or owner filters."""
        return self._store.list_cubes(scope_type=scope_type, owner_id=owner_id)

    def delete_cube(self, cube_id: str) -> bool:
        """Delete an existing cube compartment."""
        return self._store.delete_cube(cube_id)

    def mount_agent_cubes(
        self,
        agent_id: str,
        readable_cube_ids: list[str],
        writable_cube_ids: list[str],
        default_write_cube_id: str | None = None,
        strict_isolation: bool = True,
    ) -> MountPolicy:
        """Configure dynamic read/write decoupled mounting policy for an agent."""
        policy = MountPolicy(
            agent_id=agent_id,
            readable_cube_ids=readable_cube_ids,
            writable_cube_ids=writable_cube_ids,
            default_write_cube_id=default_write_cube_id,
            strict_isolation=strict_isolation,
        )
        return self._router.register_policy(policy)

    def get_agent_mount_policy(self, agent_id: str) -> MountPolicy | None:
        """Retrieve active mount topology policy for an agent."""
        return self._router.get_policy(agent_id)

    def list_agent_mount_policies(self) -> list[MountPolicy]:
        """List all active agent mount topology policies."""
        return self._router.list_policies()

    def query_cubes(self, request: CubeQueryRequest) -> CubeQueryResult:
        """Execute federated query across permitted cubes."""
        return self._router.read_federated(self._store, request)

    def write_to_cube(self, request: CubeWriteRequest) -> CubeWriteResult:
        """Deposit memory into authorized target cube."""
        return self._router.write_routed(self._store, request)

    def list_cube_records(self, cube_id: str, limit: int = 50) -> list[CubeMemoryRecord]:
        """List records stored inside a cube."""
        return self._store.list_records(cube_id=cube_id, limit=limit)

    def delete_cube_record(self, cube_id: str, record_id: str) -> bool:
        """Delete a single memory record from a cube."""
        return self._store.delete_record(cube_id=cube_id, record_id=record_id)
