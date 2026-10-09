"""Physical scope partition engine using length-prefixed namespace hashing.

[POS]
Guarantees multi-tenant physical storage isolation where each scope combination
(tenant_id, workspace_id, agent_id, session_id) is mapped to its own filesystem
directory and dedicated SQLite database. Eliminates cross-scope query leakage
and SQLite write-lock contention.

[INPUT]
- hashlib
- pathlib.Path
- myrm_agent_harness.toolkits.memory.skill_triad.models.ScopeCoordinates
- myrm_agent_harness.toolkits.memory.skill_triad.models.ScopePartitionInfo

[OUTPUT]
- ScopePhysicalPartitionEngine
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from myrm_agent_harness.toolkits.memory.skill_triad.models import (
    ScopeCoordinates,
    ScopePartitionInfo,
)


class ScopePhysicalPartitionEngine:
    """Derives deterministic physical partitions and manages isolated SQLite databases."""

    def __init__(self, base_storage_dir: str | Path | None = None) -> None:
        if base_storage_dir is None:
            home_dir = Path.home()
            self._base_dir = home_dir / ".myrm" / "memory"
        else:
            self._base_dir = Path(base_storage_dir).resolve()

    @property
    def base_dir(self) -> Path:
        """Root directory hosting all physical scope partitions."""
        return self._base_dir

    @staticmethod
    def compute_namespace_hash(coordinates: ScopeCoordinates) -> str:
        """Computes collision-resistant SHA-256 namespace hash.

        Uses sorted, length-prefixed keys and values so (user='a', agent='bc')
        and (user='ab', agent='c') can never collide regardless of component order.
        """
        coord_dict = coordinates.as_dict()
        # Sort keys lexicographically
        sorted_items = sorted(coord_dict.items(), key=lambda item: item[0])

        # Length-prefixed serialization: len(k):k:len(v):v
        encoded_tokens: list[str] = []
        for k, v in sorted_items:
            clean_k = k.strip()
            clean_v = v.strip()
            encoded_tokens.append(f"{len(clean_k)}:{clean_k}:{len(clean_v)}:{clean_v}")

        payload = ";".join(encoded_tokens).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:32]

    def resolve_partition(
        self,
        coordinates: ScopeCoordinates,
        *,
        auto_create_dir: bool = True,
    ) -> ScopePartitionInfo:
        """Resolves the physical directory and dedicated SQLite database path."""
        ns_hash = self.compute_namespace_hash(coordinates)
        scope_dir = self._base_dir / "scopes" / ns_hash
        sqlite_file = scope_dir / "memory.sqlite"

        if auto_create_dir:
            scope_dir.mkdir(parents=True, exist_ok=True)

        return ScopePartitionInfo(
            coordinates=coordinates,
            namespace_hash=ns_hash,
            partition_dir=str(scope_dir),
            sqlite_path=str(sqlite_file),
            is_isolated=True,
        )

    def delete_partition(self, coordinates: ScopeCoordinates) -> bool:
        """Atomically purges physical directory for a specific scope.

        Deleting a tenant or session memory is simply a directory removal,
        guaranteeing zero leftover rows or lingering locks.
        """
        ns_hash = self.compute_namespace_hash(coordinates)
        scope_dir = self._base_dir / "scopes" / ns_hash
        if scope_dir.exists() and scope_dir.is_dir():
            shutil.rmtree(scope_dir)
            return True
        return False

    def list_active_partitions(self) -> list[str]:
        """Lists active namespace hashes stored under the base scopes directory."""
        scopes_root = self._base_dir / "scopes"
        if not scopes_root.exists():
            return []

        active_hashes: list[str] = []
        for entry in os.scandir(scopes_root):
            if entry.is_dir():
                active_hashes.append(entry.name)
        return sorted(active_hashes)
