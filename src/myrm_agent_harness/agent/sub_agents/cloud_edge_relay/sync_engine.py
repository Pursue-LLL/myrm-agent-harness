"""Hybrid Artifact Sync Engine supporting bidirectional incremental append (Item 58).

[INPUT]
- Artifact chunks and append operations from local and cloud sandboxes.

[OUTPUT]
- CAS-versioned HybridArtifactState with append-only integrity and full provenance.

[POS]
- Core synchronization engine allowing cloud and local agents to append to the same
  table or document without destructive overwrites.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Mapping, Sequence

from myrm_agent_harness.agent.sub_agents.cloud_edge_relay.types import (
    ArtifactSyncChunk,
    HybridArtifactState,
    RelayNodeRoleEnum,
)


class HybridArtifactSyncEngine:
    """Manages versioned bidirectional append-only synchronization of shared artifacts."""

    def __init__(self) -> None:
        self._artifacts: dict[str, HybridArtifactState] = {}
        self._artifact_names: dict[str, str] = {}

    def register_artifact(
        self,
        artifact_id: str,
        name: str,
        initial_content: str = "",
        initial_rows: int = 0,
        author_role: RelayNodeRoleEnum = RelayNodeRoleEnum.LOCAL_SANDBOX,
    ) -> HybridArtifactState:
        """Initializes a shared hybrid artifact with baseline content."""
        now = time.time()
        self._artifact_names[artifact_id] = name

        chunks: list[ArtifactSyncChunk] = []
        current_rows = initial_rows

        if initial_content:
            checksum = hashlib.sha256(initial_content.encode("utf-8")).hexdigest()[:12]
            if current_rows == 0:
                current_rows = len([line for line in initial_content.splitlines() if line.strip()])
            initial_chunk = ArtifactSyncChunk(
                chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
                artifact_id=artifact_id,
                version=1,
                author_role=author_role,
                content_delta=initial_content,
                row_count=current_rows,
                timestamp=now,
                checksum=checksum,
            )
            chunks.append(initial_chunk)

        state = HybridArtifactState(
            artifact_id=artifact_id,
            name=name,
            current_version=len(chunks),
            total_rows=current_rows,
            chunks=tuple(chunks),
            last_synced_at=now,
            is_divergent=False,
        )
        self._artifacts[artifact_id] = state
        return state

    def append_chunk(
        self,
        artifact_id: str,
        content_delta: str,
        author_role: RelayNodeRoleEnum,
        expected_version: int | None = None,
        row_count: int | None = None,
    ) -> HybridArtifactState:
        """Appends an incremental delta chunk with CAS version check."""
        if artifact_id not in self._artifacts:
            raise KeyError(f"Artifact '{artifact_id}' does not exist in sync engine.")

        current = self._artifacts[artifact_id]

        # Enforce optimistic CAS concurrency check if specified
        if expected_version is not None and expected_version != current.current_version:
            raise ValueError(
                f"CAS version conflict for artifact '{artifact_id}': "
                f"expected v{expected_version}, but current is v{current.current_version}."
            )

        now = time.time()
        checksum = hashlib.sha256(content_delta.encode("utf-8")).hexdigest()[:12]
        delta_rows = (
            row_count
            if row_count is not None
            else len([line for line in content_delta.splitlines() if line.strip()])
        )

        next_version = current.current_version + 1
        new_chunk = ArtifactSyncChunk(
            chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
            artifact_id=artifact_id,
            version=next_version,
            author_role=author_role,
            content_delta=content_delta,
            row_count=delta_rows,
            timestamp=now,
            checksum=checksum,
        )

        new_chunks = list(current.chunks)
        new_chunks.append(new_chunk)

        updated_state = HybridArtifactState(
            artifact_id=artifact_id,
            name=current.name,
            current_version=next_version,
            total_rows=current.total_rows + delta_rows,
            chunks=tuple(new_chunks),
            last_synced_at=now,
            is_divergent=False,
        )
        self._artifacts[artifact_id] = updated_state
        return updated_state

    def get_aggregated_content(self, artifact_id: str) -> str:
        """Reconstructs the full content of an artifact across all sequential chunks."""
        if artifact_id not in self._artifacts:
            raise KeyError(f"Artifact '{artifact_id}' not found.")
        return "\n".join(chunk.content_delta for chunk in self._artifacts[artifact_id].chunks)

    def get_artifact_state(self, artifact_id: str) -> HybridArtifactState:
        """Retrieves the current metadata snapshot of an artifact."""
        if artifact_id not in self._artifacts:
            raise KeyError(f"Artifact '{artifact_id}' not found.")
        return self._artifacts[artifact_id]

    def list_artifacts(self) -> Mapping[str, HybridArtifactState]:
        """Returns all tracked artifacts in the sync engine."""
        return dict(self._artifacts)

    def get_provenance_summary(self, artifact_id: str) -> Sequence[Mapping[str, str | int | float]]:
        """Returns the chronological provenance timeline for an artifact."""
        if artifact_id not in self._artifacts:
            raise KeyError(f"Artifact '{artifact_id}' not found.")
        state = self._artifacts[artifact_id]
        return tuple(
            {
                "chunk_id": c.chunk_id,
                "version": c.version,
                "author_role": c.author_role.value,
                "row_count": c.row_count,
                "checksum": c.checksum,
                "timestamp": c.timestamp,
            }
            for c in state.chunks
        )

    def clear(self) -> None:
        """Resets all tracked artifacts."""
        self._artifacts.clear()
        self._artifact_names.clear()
