"""[POS]: src/myrm_agent_harness/toolkits/memory/revocable_provenance/dream_diary_recorder.py
[INPUT]: Background memory distillation events, scanned turn counts, and promotion outcomes.
[OUTPUT]: DreamDiaryRecorder maintaining an auditable transparent timeline of dreaming memory consolidation cycles.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Literal

from .models import ProvenanceDreamDiaryEntry


class DreamDiaryRecorder:
    """Records and presents background dreaming memory consolidation cycles for transparent inspection."""

    def __init__(self, diary_dir: Path | str | None = None) -> None:
        self._diary_dir = Path(diary_dir or "/tmp/myrm_dream_diaries")
        self._diary_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._entries: list[ProvenanceDreamDiaryEntry] = []
        self._load_entries()

    def record_dream(
        self,
        agent_id: str,
        scanned_turns: int,
        promoted_memory_ids: list[str] | None = None,
        pruned_duplicates_count: int = 0,
        duration_ms: float = 0.0,
        status: Literal["completed", "skipped", "failed"] = "completed",
        notes: str = "",
    ) -> ProvenanceDreamDiaryEntry:
        """Appends a new dreaming consolidation session entry to the diary."""
        entry = ProvenanceDreamDiaryEntry(
            dream_id=f"dream_{uuid.uuid4().hex[:8]}",
            agent_id=agent_id.strip(),
            scanned_turns=scanned_turns,
            promoted_memory_ids=promoted_memory_ids or [],
            pruned_duplicates_count=pruned_duplicates_count,
            duration_ms=duration_ms,
            status=status,
            notes=notes.strip(),
            created_at=datetime.now(UTC),
        )

        with self._lock:
            self._entries.append(entry)
            self._persist_entry(entry)
            return entry

    def list_entries(
        self,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[ProvenanceDreamDiaryEntry]:
        """Lists recorded dream diary entries in reverse chronological order."""
        with self._lock:
            filtered = self._entries
            if agent_id:
                target_agent = agent_id.strip()
                filtered = [e for e in self._entries if e.agent_id == target_agent]

            sorted_entries = sorted(filtered, key=lambda e: e.created_at, reverse=True)
            return sorted_entries[:limit]

    def _persist_entry(self, entry: ProvenanceDreamDiaryEntry) -> None:
        """Persists a single dream diary entry to disk as JSON."""
        target_file = self._diary_dir / f"{entry.dream_id}.json"
        data = {
            "dream_id": entry.dream_id,
            "agent_id": entry.agent_id,
            "scanned_turns": entry.scanned_turns,
            "promoted_memory_ids": entry.promoted_memory_ids,
            "pruned_duplicates_count": entry.pruned_duplicates_count,
            "duration_ms": entry.duration_ms,
            "status": entry.status,
            "notes": entry.notes,
            "created_at": entry.created_at.isoformat(),
        }
        target_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_entries(self) -> None:
        """Loads historical entries from disk on startup."""
        for p in self._diary_dir.glob("dream_*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                entry = ProvenanceDreamDiaryEntry(
                    dream_id=data["dream_id"],
                    agent_id=data["agent_id"],
                    scanned_turns=data.get("scanned_turns", 0),
                    promoted_memory_ids=data.get("promoted_memory_ids", []),
                    pruned_duplicates_count=data.get("pruned_duplicates_count", 0),
                    duration_ms=data.get("duration_ms", 0.0),
                    status=data.get("status", "completed"),
                    notes=data.get("notes", ""),
                    created_at=datetime.fromisoformat(data["created_at"]),
                )
                self._entries.append(entry)
            except Exception:
                continue
