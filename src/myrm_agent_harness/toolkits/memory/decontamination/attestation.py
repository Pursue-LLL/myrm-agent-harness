"""[POS]: src/myrm_agent_harness/toolkits/memory/decontamination/attestation.py
[INPUT]: Memory identity, origin metadata, and evidence text snippets.
[OUTPUT]: ProvenanceAttestationManager issuing and verifying cryptographic memory origin vouchers.
"""

import hashlib
import sqlite3
import time
import uuid
from pathlib import Path

from .models import MemoryProvenanceAttestation, ProvenanceSourceKind


class ProvenanceAttestationManager:
    """Manages generation, signature verification, and indexing of memory provenance attestations."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA busy_timeout = 5000;")
            self._init_schema(self._conn)
        return self._conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS myrm_memory_attestations (
                attestation_id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL UNIQUE,
                source_kind TEXT NOT NULL,
                session_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                evidence_snippet TEXT NOT NULL,
                author_identity TEXT NOT NULL,
                sha256_signature TEXT NOT NULL,
                created_at_epoch REAL NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_attest_session
            ON myrm_memory_attestations(session_id, created_at_epoch DESC);
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_attest_memory
            ON myrm_memory_attestations(memory_id);
            """
        )
        conn.commit()

    @staticmethod
    def compute_signature(
        memory_id: str,
        session_id: str,
        turn_index: int,
        source_kind: str,
        evidence_snippet: str,
    ) -> str:
        """Compute tamper-evident SHA-256 signature for provenance verification."""
        material = f"{memory_id}|{session_id}|{turn_index}|{source_kind}|{evidence_snippet}".encode()
        return hashlib.sha256(material).hexdigest()

    def issue_attestation(
        self,
        memory_id: str,
        source_kind: ProvenanceSourceKind,
        session_id: str,
        turn_index: int = 0,
        evidence_snippet: str = "",
        author_identity: str = "user",
    ) -> MemoryProvenanceAttestation:
        """Issue and record a verifiable provenance attestation for a memory entry."""
        attestation_id = f"attest_{uuid.uuid4().hex[:12]}"
        now = time.time()
        signature = self.compute_signature(
            memory_id=memory_id,
            session_id=session_id,
            turn_index=turn_index,
            source_kind=source_kind.value,
            evidence_snippet=evidence_snippet,
        )

        conn = self._get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO myrm_memory_attestations
            (attestation_id, memory_id, source_kind, session_id, turn_index,
             evidence_snippet, author_identity, sha256_signature, created_at_epoch)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                attestation_id,
                memory_id,
                source_kind.value,
                session_id,
                turn_index,
                evidence_snippet,
                author_identity,
                signature,
                now,
            ),
        )
        conn.commit()

        return MemoryProvenanceAttestation(
            attestation_id=attestation_id,
            memory_id=memory_id,
            source_kind=source_kind,
            session_id=session_id,
            turn_index=turn_index,
            evidence_snippet=evidence_snippet,
            author_identity=author_identity,
            sha256_signature=signature,
            created_at_epoch=now,
        )

    def verify_attestation(self, attestation: MemoryProvenanceAttestation) -> bool:
        """Verify cryptographic integrity of an issued attestation voucher."""
        expected_sig = self.compute_signature(
            memory_id=attestation.memory_id,
            session_id=attestation.session_id,
            turn_index=attestation.turn_index,
            source_kind=attestation.source_kind.value,
            evidence_snippet=attestation.evidence_snippet,
        )
        return expected_sig == attestation.sha256_signature

    def get_attestation(self, memory_id: str) -> MemoryProvenanceAttestation | None:
        """Retrieve attestation record by memory ID."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT attestation_id, memory_id, source_kind, session_id, turn_index,
                   evidence_snippet, author_identity, sha256_signature, created_at_epoch
            FROM myrm_memory_attestations
            WHERE memory_id = ?;
            """,
            (memory_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return MemoryProvenanceAttestation(
            attestation_id=str(row["attestation_id"]),
            memory_id=str(row["memory_id"]),
            source_kind=ProvenanceSourceKind(row["source_kind"]),
            session_id=str(row["session_id"]),
            turn_index=int(row["turn_index"]),
            evidence_snippet=str(row["evidence_snippet"]),
            author_identity=str(row["author_identity"]),
            sha256_signature=str(row["sha256_signature"]),
            created_at_epoch=float(row["created_at_epoch"]),
        )

    def list_attestations_by_session(self, session_id: str) -> list[MemoryProvenanceAttestation]:
        """List all provenance attestations generated during a specific session."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT attestation_id, memory_id, source_kind, session_id, turn_index,
                   evidence_snippet, author_identity, sha256_signature, created_at_epoch
            FROM myrm_memory_attestations
            WHERE session_id = ?
            ORDER BY turn_index ASC, created_at_epoch ASC;
            """,
            (session_id,),
        )
        rows = cursor.fetchall()
        return [
            MemoryProvenanceAttestation(
                attestation_id=str(r["attestation_id"]),
                memory_id=str(r["memory_id"]),
                source_kind=ProvenanceSourceKind(r["source_kind"]),
                session_id=str(r["session_id"]),
                turn_index=int(r["turn_index"]),
                evidence_snippet=str(r["evidence_snippet"]),
                author_identity=str(r["author_identity"]),
                sha256_signature=str(r["sha256_signature"]),
                created_at_epoch=float(r["created_at_epoch"]),
            )
            for r in rows
        ]
