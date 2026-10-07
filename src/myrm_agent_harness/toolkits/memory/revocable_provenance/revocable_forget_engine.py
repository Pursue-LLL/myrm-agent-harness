"""[POS]: src/myrm_agent_harness/toolkits/memory/revocable_provenance/revocable_forget_engine.py
[INPUT]: ProvenanceMemoryStore, memory identifiers, revocation reasons, and candidate facts.
[OUTPUT]: RevocableForgetEngine performing atomic point revocation and preventing zombie resurfacing without corrupting raw transcripts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from .models import ForgetResult
from .provenance_store import ProvenanceMemoryStore


class RevocableForgetEngine:
    """Performs atomic point memory revocation and maintains tombstone exclusion fingerprints."""

    def __init__(
        self,
        store: ProvenanceMemoryStore,
        tombstone_dir: Path | str | None = None,
    ) -> None:
        self._store = store
        self._tombstone_dir = Path(tombstone_dir or "/tmp/myrm_provenance_tombstones")
        self._tombstone_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        # fingerprint string -> revocation metadata dict
        self._tombstone_fingerprints: dict[str, dict[str, str]] = {}
        self._load_tombstones()

    def forget(self, memory_id: str, reason: str = "") -> ForgetResult:
        """Atomically revokes a promoted memory entry, registering its tombstone to prevent resurrection."""
        with self._lock:
            memory = self._store.get_memory(memory_id)
            if memory is None:
                return ForgetResult(
                    memory_id=memory_id,
                    revoked=False,
                    source_session_id="",
                    source_message_id="",
                    message=f"Memory '{memory_id}' not found in store.",
                    transcript_intact=True,
                )

            if memory.is_revoked:
                return ForgetResult(
                    memory_id=memory_id,
                    revoked=True,
                    source_session_id=memory.provenance.session_id,
                    source_message_id=memory.provenance.message_id,
                    message=f"Memory '{memory_id}' was already revoked.",
                    transcript_intact=True,
                )

            # 1. Update memory state to revoked
            now = datetime.now(UTC)
            memory.is_revoked = True
            memory.revoked_at = now
            memory.revocation_reason = reason or "Revoked by user via memory forget"
            memory.updated_at = now
            self._store.save_memory(memory)

            # 2. Register tombstone exclusion fingerprint
            fp = memory.fingerprint
            tombstone_info = {
                "memory_id": memory.memory_id,
                "session_id": memory.provenance.session_id,
                "message_id": memory.provenance.message_id,
                "statement": memory.statement,
                "reason": memory.revocation_reason,
                "revoked_at": now.isoformat(),
            }
            self._tombstone_fingerprints[fp] = tombstone_info
            self._persist_tombstone(fp, tombstone_info)

            return ForgetResult(
                memory_id=memory.memory_id,
                revoked=True,
                source_session_id=memory.provenance.session_id,
                source_message_id=memory.provenance.message_id,
                message=f"Successfully revoked memory '{memory_id}'. Raw transcript left intact.",
                transcript_intact=True,
            )

    def is_excluded(self, session_id: str, message_id: str, statement: str) -> bool:
        """Checks if a candidate statement has been previously revoked for this source turn."""
        fp = f"{session_id.strip()}:{message_id.strip()}:{statement.strip().lower()}"
        with self._lock:
            return fp in self._tombstone_fingerprints

    def list_tombstones(self) -> list[dict[str, str]]:
        """Lists all registered tombstone exclusions."""
        with self._lock:
            return list(self._tombstone_fingerprints.values())

    def _persist_tombstone(self, fingerprint: str, info: dict[str, str]) -> None:
        """Persists tombstone record to disk."""
        safe_name = fingerprint.replace(":", "_").replace("/", "_")[:64]
        target_file = self._tombstone_dir / f"tomb_{safe_name}.json"
        target_file.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_tombstones(self) -> None:
        """Loads existing tombstone records from disk during initialization."""
        for p in self._tombstone_dir.glob("tomb_*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                session_id = data.get("session_id", "")
                message_id = data.get("message_id", "")
                statement = data.get("statement", "")
                if session_id and message_id and statement:
                    fp = f"{session_id}:{message_id}:{statement.strip().lower()}"
                    self._tombstone_fingerprints[fp] = data
            except Exception:
                continue
