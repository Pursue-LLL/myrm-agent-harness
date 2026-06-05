"""PseudonymStore — local SQLite mapping of original PII to typed placeholders.

Maintains a persistent, per-user mapping between original sensitive text
and semantically typed pseudonyms (e.g. ``<PHONE_NUMBER_1>``).

Design rationale:
  - Independent SQLite DB (not shared with memory system) — security
    subsystem must have zero external dependencies on other toolkits.
  - WAL mode for concurrent read safety.
  - Thread-safe via ``check_same_thread=False`` + connection-per-call
    for write serialization.
  - get_or_create is idempotent: same original_text always returns the
    same pseudonym across sessions.

[INPUT]

[OUTPUT]
- PseudonymStore: persistent pseudonym mapping backed by SQLite
- get_pseudonym_store(): module-level factory (singleton per db_path)

[POS]
Local SQLite store for reversible PII pseudonymization. Maps
original_text to typed placeholders (<TYPE_N>) with cross-session
persistence.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass

_PSEUDONYM_RE = re.compile(r"<([A-Z][A-Z_]*[A-Z])_(\d+)>")


@dataclass(frozen=True, slots=True)
class PseudonymEntry:
    """A single original_text ↔ pseudonym mapping."""

    original_text: str
    privacy_type: str
    sensitivity_level: str
    pseudonym: str


class PseudonymStore:
    """Persistent pseudonym mapping backed by SQLite.

    Each entry maps ``original_text`` to a unique typed placeholder
    like ``<PHONE_NUMBER_1>``.  The mapping is cross-session persistent
    so the same PII always resolves to the same pseudonym.
    """

    __slots__ = ("_conn", "_db_path", "_lock")

    def __init__(self, db_path: str) -> None:
        from pathlib import Path

        from myrm_agent_harness.utils.db.sqlite import (
            SENSITIVE,
            harden_connection_sync,
            prepare_database_file,
        )

        self._db_path = db_path
        self._lock = threading.Lock()
        prepare_database_file(Path(db_path))
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        harden_connection_sync(self._conn, SENSITIVE, db_path=Path(db_path))
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pseudonyms (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                original_text    TEXT    NOT NULL UNIQUE,
                privacy_type     TEXT    NOT NULL,
                sensitivity_level TEXT   NOT NULL,
                pseudonym        TEXT    NOT NULL UNIQUE
            )
        """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_pseudonyms_type ON pseudonyms(privacy_type)")
        self._conn.commit()

    def _next_pseudonym(self, privacy_type: str) -> str:
        """Generate the next pseudonym for a given type (e.g. <PHONE_NUMBER_2>)."""
        tag = privacy_type.upper().replace(" ", "_").replace("/", "_")
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM pseudonyms WHERE privacy_type = ?",
            (privacy_type,),
        ).fetchone()
        seq = (row["cnt"] or 0) + 1
        return f"<{tag}_{seq}>"

    def get_or_create(
        self,
        original_text: str,
        privacy_type: str,
        sensitivity_level: str,
    ) -> str:
        """Return the pseudonym for *original_text*, creating one if needed.

        Thread-safe.  Idempotent: repeated calls with the same
        ``original_text`` always return the same pseudonym.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT pseudonym FROM pseudonyms WHERE original_text = ?",
                (original_text,),
            ).fetchone()
            if row:
                return row["pseudonym"]

            pseudonym = self._next_pseudonym(privacy_type)
            self._conn.execute(
                "INSERT INTO pseudonyms "
                "(original_text, privacy_type, sensitivity_level, pseudonym) "
                "VALUES (?, ?, ?, ?)",
                (original_text, privacy_type, sensitivity_level, pseudonym),
            )
            self._conn.commit()
            return pseudonym

    def resolve(self, pseudonym: str) -> str | None:
        """Look up the original text for a pseudonym. Returns None if unknown."""
        row = self._conn.execute(
            "SELECT original_text FROM pseudonyms WHERE pseudonym = ?",
            (pseudonym,),
        ).fetchone()
        return row["original_text"] if row else None

    def resolve_all(self, text: str) -> str:
        """Replace all ``<TYPE_N>`` pseudonyms in *text* with original values."""

        def _replace(match: re.Match[str]) -> str:
            token = match.group(0)
            original = self.resolve(token)
            return original if original is not None else token

        return _PSEUDONYM_RE.sub(_replace, text)

    def stats(self) -> dict[str, int]:
        """Return entry counts grouped by privacy_type."""
        rows = self._conn.execute(
            "SELECT privacy_type, COUNT(*) AS cnt FROM pseudonyms GROUP BY privacy_type"
        ).fetchall()
        return {row["privacy_type"]: row["cnt"] for row in rows}

    def close(self) -> None:
        from myrm_agent_harness.utils.db.sqlite import checkpoint_truncate_sync

        checkpoint_truncate_sync(self._conn)
        self._conn.close()


_stores: dict[str, PseudonymStore] = {}
_stores_lock = threading.Lock()


def get_pseudonym_store(db_path: str) -> PseudonymStore:
    """Get or create a PseudonymStore singleton for *db_path*.

    Callers must supply a concrete path.  Typical usage from the business
    layer::

        store = get_pseudonym_store(str(base_path / "pseudonym_store.db"))
    """
    with _stores_lock:
        store = _stores.get(db_path)
        if store is None:
            import os

            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            store = PseudonymStore(db_path)
            _stores[db_path] = store
        return store
