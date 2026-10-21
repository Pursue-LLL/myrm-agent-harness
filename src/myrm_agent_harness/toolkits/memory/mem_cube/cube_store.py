"""In-memory isolated storage engine for Memory Cubes and scoped records.

[INPUT]
- collections.abc.Sequence
- datetime (datetime, UTC)
- threading (RLock)
- uuid (uuid4)
- .models::{CubeMemoryRecord, CubeScopeType, MemoryCube}

[OUTPUT]
- MemoryCubeStore: Thread-safe storage container managing isolated cube namespaces.

[POS]
Core storage layer for Item 124 (MemoryCubeScopedIsolationAndDynamicMountingSuite).
"""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from myrm_agent_harness.toolkits.memory.mem_cube.models import (
    CubeMemoryRecord,
    CubeScopeType,
    MemoryCube,
)


class MemoryCubeStore:
    """Thread-safe isolated memory store maintaining segregated MemoryCube partitions."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._cubes: dict[str, MemoryCube] = {}
        self._records: dict[str, dict[str, CubeMemoryRecord]] = {}
        self._initialize_default_cubes()

    def _initialize_default_cubes(self) -> None:
        """Seed default global shared and general workspace cubes."""
        now_iso = datetime.now(UTC).isoformat()
        global_cube = MemoryCube(
            cube_id="cube-global-shared",
            name="全局通用知识与偏好 Cube",
            scope_type=CubeScopeType.GLOBAL_SHARED,
            owner_id="system",
            description="跨所有智能体与工程共享的基础常识、全局用户偏好与通用代码规范。",
            is_read_only=False,
            created_at_iso=now_iso,
            tags=["global", "shared", "standards"],
            item_count=0,
        )
        self._cubes[global_cube.cube_id] = global_cube
        self._records[global_cube.cube_id] = {}

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
        """Create and register a new MemoryCube compartment."""
        with self._lock:
            cid = cube_id or f"cube-{scope_type.value}-{uuid4().hex[:8]}"
            if cid in self._cubes:
                raise ValueError(f"MemoryCube with ID '{cid}' already exists.")

            cube = MemoryCube(
                cube_id=cid,
                name=name,
                scope_type=scope_type,
                owner_id=owner_id,
                description=description,
                is_read_only=is_read_only,
                created_at_iso=datetime.now(UTC).isoformat(),
                tags=tags or [],
                item_count=0,
            )
            self._cubes[cid] = cube
            self._records[cid] = {}
            return cube

    def get_cube(self, cube_id: str) -> MemoryCube | None:
        """Retrieve cube metadata by ID."""
        with self._lock:
            return self._cubes.get(cube_id)

    def list_cubes(
        self,
        scope_type: CubeScopeType | None = None,
        owner_id: str | None = None,
    ) -> list[MemoryCube]:
        """List cubes matching optional scope or owner filters."""
        with self._lock:
            results = list(self._cubes.values())
            if scope_type is not None:
                results = [c for c in results if c.scope_type == scope_type]
            if owner_id is not None:
                results = [c for c in results if c.owner_id == owner_id]
            return sorted(results, key=lambda c: c.created_at_iso)

    def delete_cube(self, cube_id: str) -> bool:
        """Delete a cube and its associated records partition."""
        with self._lock:
            if cube_id not in self._cubes:
                return False
            del self._cubes[cube_id]
            self._records.pop(cube_id, None)
            return True

    def store_record(
        self,
        cube_id: str,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, str] | None = None,
        record_id: str | None = None,
    ) -> CubeMemoryRecord:
        """Store a scoped memory record into the designated cube."""
        with self._lock:
            cube = self._cubes.get(cube_id)
            if cube is None:
                raise KeyError(f"Target MemoryCube '{cube_id}' does not exist.")
            if cube.is_read_only:
                raise PermissionError(f"Target MemoryCube '{cube_id}' is marked read-only.")

            rid = record_id or f"rec-{uuid4().hex[:12]}"
            record = CubeMemoryRecord(
                record_id=rid,
                cube_id=cube_id,
                content=content,
                importance=importance,
                created_at_iso=datetime.now(UTC).isoformat(),
                metadata=metadata or {},
            )

            partition = self._records.setdefault(cube_id, {})
            partition[rid] = record
            cube.item_count = len(partition)
            return record

    def get_record(self, cube_id: str, record_id: str) -> CubeMemoryRecord | None:
        """Retrieve a single record from a specific cube."""
        with self._lock:
            partition = self._records.get(cube_id, {})
            return partition.get(record_id)

    def list_records(self, cube_id: str, limit: int = 50) -> list[CubeMemoryRecord]:
        """List records belonging strictly to a single cube."""
        with self._lock:
            partition = self._records.get(cube_id, {})
            records = list(partition.values())
            records.sort(key=lambda r: (r.importance, r.created_at_iso), reverse=True)
            return records[:limit]

    def query_records(
        self,
        cube_id: str,
        query: str,
        limit: int = 10,
    ) -> list[CubeMemoryRecord]:
        """Search records within a specific cube matching query tokens."""
        with self._lock:
            partition = self._records.get(cube_id, {})
            if not partition:
                return []

            q_lower = query.strip().lower()
            tokens = [t for t in q_lower.split() if len(t) > 1]
            scored: list[tuple[float, CubeMemoryRecord]] = []

            for rec in partition.values():
                c_lower = rec.content.lower()
                if not tokens:
                    score = rec.importance
                else:
                    match_count = sum(1 for t in tokens if t in c_lower)
                    if match_count == 0:
                        continue
                    token_overlap = match_count / len(tokens)
                    score = (token_overlap * 0.7) + (rec.importance * 0.3)
                scored.append((score, rec))

            scored.sort(key=lambda item: item[0], reverse=True)
            return [rec for _, rec in scored[:limit]]

    def delete_record(self, cube_id: str, record_id: str) -> bool:
        """Remove a record from a cube and decrement item count."""
        with self._lock:
            partition = self._records.get(cube_id)
            if partition is None or record_id not in partition:
                return False
            del partition[record_id]
            cube = self._cubes.get(cube_id)
            if cube is not None:
                cube.item_count = len(partition)
            return True
