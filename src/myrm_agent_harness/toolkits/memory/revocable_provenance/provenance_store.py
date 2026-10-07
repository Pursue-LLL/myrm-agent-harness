"""[POS]: src/myrm_agent_harness/toolkits/memory/revocable_provenance/provenance_store.py
[INPUT]: ProvenanceQualifiedMemory models, storage directories, and query parameters.
[OUTPUT]: ProvenanceMemoryStore providing bi-directional indexing between raw chat sources and promoted memories.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from .models import ProvenanceQualifiedMemory


class ProvenanceMemoryStore:
    """Stores and indexes long-term memories with bidirectional traceability to source transcripts."""

    def __init__(self, storage_dir: Path | str | None = None) -> None:
        self._storage_dir = Path(storage_dir or "/tmp/myrm_provenance_memory")
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        # memory_id -> ProvenanceQualifiedMemory
        self._memories: dict[str, ProvenanceQualifiedMemory] = {}
        # session_id -> set of memory_id
        self._session_index: dict[str, set[str]] = {}
        # message_id -> set of memory_id
        self._message_index: dict[str, set[str]] = {}

    def save_memory(self, memory: ProvenanceQualifiedMemory) -> ProvenanceQualifiedMemory:
        """Saves a provenance-qualified memory and updates bidirectional index entries."""
        with self._lock:
            self._memories[memory.memory_id] = memory
            session_id = memory.provenance.session_id
            message_id = memory.provenance.message_id

            self._session_index.setdefault(session_id, set()).add(memory.memory_id)
            self._message_index.setdefault(message_id, set()).add(memory.memory_id)

            self._persist_to_disk(memory)
            return memory

    def get_memory(self, memory_id: str) -> ProvenanceQualifiedMemory | None:
        """Retrieves a memory entry by its unique identifier."""
        with self._lock:
            return self._memories.get(memory_id)

    def list_memories(self, include_revoked: bool = False) -> list[ProvenanceQualifiedMemory]:
        """Lists stored memories, optionally filtering out revoked items."""
        with self._lock:
            if include_revoked:
                return list(self._memories.values())
            return [m for m in self._memories.values() if not m.is_revoked]

    def find_by_session(
        self, session_id: str, include_revoked: bool = False
    ) -> list[ProvenanceQualifiedMemory]:
        """Finds all memories derived from the specified source chat session."""
        with self._lock:
            memory_ids = self._session_index.get(session_id, set())
            results: list[ProvenanceQualifiedMemory] = []
            for mid in memory_ids:
                mem = self._memories.get(mid)
                if mem and (include_revoked or not mem.is_revoked):
                    results.append(mem)
            return sorted(results, key=lambda m: m.provenance.turn_index)

    def find_by_message(
        self, message_id: str, include_revoked: bool = False
    ) -> list[ProvenanceQualifiedMemory]:
        """Finds all memories originating specifically from a given message turn."""
        with self._lock:
            memory_ids = self._message_index.get(message_id, set())
            results: list[ProvenanceQualifiedMemory] = []
            for mid in memory_ids:
                mem = self._memories.get(mid)
                if mem and (include_revoked or not mem.is_revoked):
                    results.append(mem)
            return results

    def _persist_to_disk(self, memory: ProvenanceQualifiedMemory) -> None:
        """Persists single memory entry state to local JSON file."""
        target_file = self._storage_dir / f"{memory.memory_id}.json"
        data = {
            "memory_id": memory.memory_id,
            "statement": memory.statement,
            "category": memory.category,
            "is_revoked": memory.is_revoked,
            "revoked_at": memory.revoked_at.isoformat() if memory.revoked_at else None,
            "revocation_reason": memory.revocation_reason,
            "created_at": memory.created_at.isoformat(),
            "updated_at": memory.updated_at.isoformat(),
            "provenance": {
                "session_id": memory.provenance.session_id,
                "message_id": memory.provenance.message_id,
                "turn_index": memory.provenance.turn_index,
                "quote_snippet": memory.provenance.quote_snippet,
                "extracted_at": memory.provenance.extracted_at.isoformat(),
                "confidence_score": memory.provenance.confidence_score,
            },
        }
        target_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
