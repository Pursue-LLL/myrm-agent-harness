"""Session entity provenance tracker preventing hallucinated or forged entity writes.

[INPUT]
- session_id, entity_id, entity_type, source_tool

[OUTPUT]
- SessionProvenanceTracker: records read tool observed entities and enforces provenance on mutate tools.
- ProvenanceCheckError: raised when an unobserved entity is mutated.

[POS]
Harness core security module inspired by Anthropic Commerce Agents (PROVENANCE_GATE).
"""

from __future__ import annotations

import threading
import time

from myrm_agent_harness.core.security.provenance_gate.types import (
    EntityProvenanceRecord,
    ProvenanceCheckError,
)


class SessionProvenanceTracker:
    """Thread-safe tracker maintaining the set of seen entities per session."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, EntityProvenanceRecord]] = {}
        self._lock = threading.Lock()

    def record_observed_entity(
        self,
        session_id: str,
        entity_id: str,
        entity_type: str = "general_entity",
        source_tool: str = "read_query",
    ) -> EntityProvenanceRecord:
        """Register an entity returned by an authenticated read-only query tool."""
        record = EntityProvenanceRecord(
            session_id=session_id,
            entity_id=entity_id,
            entity_type=entity_type,
            source_tool=source_tool,
            observed_at=time.time(),
        )
        with self._lock:
            if session_id not in self._records:
                self._records[session_id] = {}
            self._records[session_id][entity_id] = record
        return record

    def record_observed_entities(
        self,
        session_id: str,
        entity_ids: list[str],
        entity_type: str = "general_entity",
        source_tool: str = "read_query",
    ) -> list[EntityProvenanceRecord]:
        """Batch register multiple entities returned from list or search tools."""
        return [
            self.record_observed_entity(
                session_id=session_id,
                entity_id=eid,
                entity_type=entity_type,
                source_tool=source_tool,
            )
            for eid in entity_ids
        ]

    def is_entity_observed(self, session_id: str, entity_id: str) -> bool:
        """Check if an entity ID has been observed in this session."""
        with self._lock:
            session_entities = self._records.get(session_id)
            if not session_entities:
                return False
            return entity_id in session_entities

    def assert_provenance(self, session_id: str, entity_id: str, tool_name: str) -> None:
        """Validate provenance; raises ProvenanceCheckError if entity was never returned by a query tool."""
        if not self.is_entity_observed(session_id, entity_id):
            raise ProvenanceCheckError(
                session_id=session_id,
                entity_id=entity_id,
                tool_name=tool_name,
            )

    def list_observed_entities(self, session_id: str) -> list[str]:
        """Return list of all observed entity IDs for a session."""
        with self._lock:
            session_entities = self._records.get(session_id)
            if not session_entities:
                return []
            return list(session_entities.keys())

    def clear_session(self, session_id: str) -> None:
        """Wipe provenance history for a terminated session."""
        with self._lock:
            self._records.pop(session_id, None)
