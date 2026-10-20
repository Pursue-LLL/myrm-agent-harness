"""Durable cron failure incidents with signature dedup and ack.

Physical separation from runtime execution logs ensures failure incidents
persist across reboots and support operator acknowledgment (ACK) silencing.
Implements the Hermes Agent v0.21.0 Pantheon architecture with zero Any types.

[OUTPUT]
- normalize_error: Strip whitespace, normalize duration fluctuations.
- redact_sensitive_error: Scrub secrets before persisting incident errors.
- calculate_error_signature: Stable hash for (job_id, normalized_error).
- classify_failure_type: Rule-based classification of failure symptoms.
- detect_false_positive: Validate expected artifacts when exit code is 0.
- SqliteIncidentStore: High-performance SQLite-backed incident store.

[INPUT]
- __future__
- asyncio
- contextlib
- hashlib
- os
- re

[OUTPUT]
- MAX_ERROR_CHARS
- MAX_SIGNATURE_ERROR_CHARS
- normalize_error
- redact_sensitive_error
- calculate_error_signature
- format_incident_id
- classify_failure_type
- detect_false_positive
- SqliteIncidentStore

[POS]
Durable cron failure incidents with signature dedup and ack.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.cron.incident_types import (
    VALID_INCIDENT_STATES,
    CronIncident,
    FailureType,
    IncidentState,
)

MAX_ERROR_CHARS: int = 500
MAX_SIGNATURE_ERROR_CHARS: int = 200

# Measured durations differ run-to-run, masked out so hashes remain identical
_DURATION_RE: re.Pattern[str] = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:ms|s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)\b",
    re.IGNORECASE,
)

_SENSITIVE_RE: re.Pattern[str] = re.compile(
    r"(?i)(bearer\s+[a-z0-9_\-\.]+)|(sk-[a-z0-9]{20,})|(password[:=]\s*\S+)"
)

_FAILURE_TYPE_ORDER: tuple[tuple[FailureType, tuple[str, ...]], ...] = (
    ("rate_limit", (r"\b429\b", "rate limit", "usage limit", "quota")),
    ("timeout", ("timeout", "timed out", "deadline exceeded")),
    ("auth", (r"\b401\b", r"\b403\b", "unauthorized", "authentication", "forbidden")),
    ("delivery", ("delivery", "deliver", "webhook failed", "smtp")),
    ("config", ("config", "configuration", "validation", "invalid argument")),
    ("script", ("script", "no_agent", "exit code", "syntaxerror")),
    ("agent", ("agent", "model", "provider", "inference", "hallucination")),
)


def normalize_error(error: str) -> str:
    """Strip whitespace and lowercase before signing."""
    return re.sub(r"\s+", " ", str(error or "")).strip().lower()


def redact_sensitive_error(error: str) -> str:
    """Scrub tokens/passwords and bound max persisted error length."""
    text = str(error or "")
    scrubbed = _SENSITIVE_RE.sub("[REDACTED]", text)
    return scrubbed[:MAX_ERROR_CHARS]


def calculate_error_signature(job_id: str, error: str) -> str:
    """Compute stable 12-char SHA256 signature for (job_id, error)."""
    normalized = _DURATION_RE.sub("#s", normalize_error(error))[:MAX_SIGNATURE_ERROR_CHARS]
    combined = job_id.encode("utf-8") + b"|" + normalized.encode("utf-8")
    return hashlib.sha256(combined).hexdigest()[:12]


def format_incident_id(job_id: str, error_sig: str) -> str:
    """Format composite incident ID."""
    prefix = job_id[:6] if len(job_id) >= 6 else job_id
    return f"{prefix}_{error_sig}"


def classify_failure_type(error: str) -> FailureType:
    """Classify failure symptom from normalized error message."""
    text = normalize_error(error)
    if not text:
        return "unknown"
    for kind, patterns in _FAILURE_TYPE_ORDER:
        for pattern in patterns:
            if pattern.startswith(r"\b") and pattern.endswith(r"\b"):
                if re.search(pattern, text):
                    return kind
            elif pattern in text:
                return kind
    return "unknown"


def detect_false_positive(
    exit_code: int,
    output_file: str | None,
) -> tuple[bool, str | None]:
    """Detect silent failures when exit code is 0 but artifact is missing."""
    if exit_code != 0 or output_file is None:
        return False, None
    out_path = Path(output_file)
    if not out_path.exists():
        return True, f"Process exited with 0 but expected output '{output_file}' does not exist"
    try:
        if os.path.getsize(out_path) == 0:
            return True, f"Process exited with 0 but expected output '{output_file}' is empty (0 bytes)"
    except OSError as err:
        return True, f"Process exited with 0 but cannot access output '{output_file}': {err}"
    return False, None


class SqliteIncidentStore:
    """Thread-safe and async-compatible SQLite storage for cron incidents."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._db_path = str(db_path)
        self._lock = asyncio.Lock()
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=30.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA synchronous = NORMAL;")
        else:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False, timeout=30.0)
            self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS cron_incidents (
                    id            TEXT PRIMARY KEY,
                    job_id        TEXT NOT NULL,
                    error_sig     TEXT NOT NULL,
                    state         TEXT NOT NULL,
                    failure_type  TEXT NOT NULL DEFAULT 'unknown',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at  TEXT NOT NULL,
                    acked_at      TEXT,
                    alerted_at    TEXT,
                    closed_at     TEXT,
                    error         TEXT NOT NULL,
                    output_file   TEXT
                )"""
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_cron_incidents_job ON cron_incidents(job_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_cron_incidents_state ON cron_incidents(state)")

    def close(self) -> None:
        """Close underlying SQLite connection."""
        with contextlib.suppress(Exception):
            self._conn.close()

    def _row_to_incident(self, row: sqlite3.Row) -> CronIncident:
        def _parse(ts: str | None) -> datetime | None:
            if not ts:
                return None
            dt = datetime.fromisoformat(ts)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

        first_seen = _parse(row["first_seen_at"])
        last_seen = _parse(row["last_seen_at"])
        if first_seen is None or last_seen is None:
            now_dt = datetime.now(UTC)
            first_seen = first_seen or now_dt
            last_seen = last_seen or now_dt

        return CronIncident(
            id=str(row["id"]),
            job_id=str(row["job_id"]),
            error_sig=str(row["error_sig"]),
            state=str(row["state"]),  # type: ignore[arg-type]
            failure_type=str(row["failure_type"]),  # type: ignore[arg-type]
            first_seen_at=first_seen,
            last_seen_at=last_seen,
            error=str(row["error"]),
            output_file=str(row["output_file"]) if row["output_file"] is not None else None,
            alerted_at=_parse(row["alerted_at"]),
            acked_at=_parse(row["acked_at"]),
            closed_at=_parse(row["closed_at"]),
        )

    async def upsert_incident(
        self,
        job_id: str,
        error: str,
        *,
        failure_type: FailureType | None = None,
        output_file: str | None = None,
    ) -> tuple[CronIncident, bool]:
        """Record or refresh incident. Returns (incident, is_new_or_reopened)."""
        async with self._lock:
            return self._sync_upsert_incident(
                job_id, error, failure_type=failure_type, output_file=output_file
            )

    def _sync_upsert_incident(
        self,
        job_id: str,
        error: str,
        *,
        failure_type: FailureType | None = None,
        output_file: str | None = None,
    ) -> tuple[CronIncident, bool]:
        sig = calculate_error_signature(job_id, error)
        incident_id = format_incident_id(job_id, sig)
        sanitized_error = redact_sensitive_error(error)
        resolved_type = failure_type or classify_failure_type(error)
        now_str = datetime.now(UTC).isoformat()

        row = self._conn.execute(
            "SELECT * FROM cron_incidents WHERE id = ?", (incident_id,)
        ).fetchone()

        if row is not None:
            current_state: str = row["state"]
            reopen = current_state == "resolved"
            new_state = "detected" if reopen else current_state
            new_alerted = None if reopen else row["alerted_at"]
            new_closed = None if reopen else row["closed_at"]

            with self._conn:
                self._conn.execute(
                    """UPDATE cron_incidents
                       SET last_seen_at = ?,
                           error = ?,
                           output_file = ?,
                           state = ?,
                           alerted_at = ?,
                           closed_at = ?
                       WHERE id = ?""",
                    (now_str, sanitized_error, output_file, new_state, new_alerted, new_closed, incident_id),
                )
            updated_row = self._conn.execute(
                "SELECT * FROM cron_incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            return self._row_to_incident(updated_row), reopen

        with self._conn:
            self._conn.execute(
                """INSERT INTO cron_incidents
                   (id, job_id, error_sig, state, failure_type, first_seen_at, last_seen_at,
                    alerted_at, acked_at, closed_at, error, output_file)
                   VALUES (?, ?, ?, 'detected', ?, ?, ?, NULL, NULL, NULL, ?, ?)""",
                (incident_id, job_id, sig, resolved_type, now_str, now_str, sanitized_error, output_file),
            )
        new_row = self._conn.execute(
            "SELECT * FROM cron_incidents WHERE id = ?", (incident_id,)
        ).fetchone()
        return self._row_to_incident(new_row), True

    async def set_incident_state(self, incident_id: str, state: IncidentState) -> bool:
        """Transition incident state. Returns True if modified."""
        if state not in VALID_INCIDENT_STATES:
            return False
        async with self._lock:
            now_str = datetime.now(UTC).isoformat()
            row = self._conn.execute(
                "SELECT state FROM cron_incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            if row is None or row["state"] == "closed":
                return False
            if state == "alerted":
                with self._conn:
                    self._conn.execute(
                        "UPDATE cron_incidents SET state = 'alerted', alerted_at = ? WHERE id = ?",
                        (now_str, incident_id),
                    )
                return True
            if row["state"] == state:
                return False
            with self._conn:
                if state == "closed":
                    self._conn.execute(
                        """UPDATE cron_incidents
                           SET state = 'closed', closed_at = ?, acked_at = ?
                           WHERE id = ? AND state != 'closed'""",
                        (now_str, now_str, incident_id),
                    )
                else:
                    self._conn.execute(
                        "UPDATE cron_incidents SET state = ? WHERE id = ?",
                        (state, incident_id),
                    )
            return True

    async def ack_incident(self, incident_id: str) -> bool:
        """Acknowledge (close) an incident to silence future identical failure pings."""
        return await self.set_incident_state(incident_id, "closed")

    async def close_incidents_for_recovered_job(self, job_id: str) -> int:
        """Mark open incidents as resolved upon successful execution."""
        async with self._lock:
            now_str = datetime.now(UTC).isoformat()
            with self._conn:
                cursor = self._conn.execute(
                    """UPDATE cron_incidents
                       SET state = 'resolved', closed_at = ?
                       WHERE job_id = ? AND state IN ('detected', 'alerted')""",
                    (now_str, job_id),
                )
                return int(cursor.rowcount or 0)

    async def list_incidents(
        self,
        *,
        state: IncidentState | None = None,
        job_id: str | None = None,
        limit: int | None = None,
    ) -> list[CronIncident]:
        """Query incidents sorted by last_seen_at descending."""
        clauses: list[str] = []
        params: list[str | int] = []
        if state is not None:
            if state not in VALID_INCIDENT_STATES:
                return []
            clauses.append("state = ?")
            params.append(state)
        if job_id is not None:
            clauses.append("job_id = ?")
            params.append(job_id)

        where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = f" LIMIT {int(limit)}" if limit is not None and limit > 0 else ""
        sql = (
            f"SELECT * FROM cron_incidents{where_sql} "
            f"ORDER BY julianday(last_seen_at) DESC, id DESC{limit_sql}"
        )

        async with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
            return [self._row_to_incident(r) for r in rows]

    async def get_incident(self, incident_id: str) -> CronIncident | None:
        """Fetch incident by identifier."""
        async with self._lock:
            row = self._conn.execute(
                "SELECT * FROM cron_incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            return self._row_to_incident(row) if row is not None else None

    async def count_incidents(
        self,
        *,
        state: IncidentState | None = None,
        job_id: str | None = None,
    ) -> int:
        """Count incidents matching optional criteria."""
        clauses: list[str] = []
        params: list[str | int] = []
        if state is not None:
            if state not in VALID_INCIDENT_STATES:
                return 0
            clauses.append("state = ?")
            params.append(state)
        if job_id is not None:
            clauses.append("job_id = ?")
            params.append(job_id)

        where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT COUNT(*) AS cnt FROM cron_incidents{where_sql}"

        async with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
            return int(row["cnt"]) if row is not None else 0

