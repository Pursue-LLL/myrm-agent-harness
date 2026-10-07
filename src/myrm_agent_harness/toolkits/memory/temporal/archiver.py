"""Fact Expiration Archiver for periodic pruning and cold-tier archiving.

[INPUT]
- toolkits.memory.temporal.models::ExpirationScanResult, FactTemporalState, TemporalFactRecord (POS: Data
  models for Temporal Validity and Fact Expiration Governance Engine.)

[OUTPUT]
- FactExpirationArchiver: Scans and quarantines expired facts from active working memory to cold storage.

[POS]
Fact Expiration Archiver for periodic pruning and cold-tier archiving.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from .models import (
    ExpirationScanResult,
    FactTemporalState,
    TemporalFactRecord,
)


class FactExpirationArchiver:
    """Scans and quarantines expired facts from active working memory to cold storage."""

    def __init__(self) -> None:
        """Initialize in-memory cold archive storage."""
        self._archive_store: dict[str, TemporalFactRecord] = {}

    @property
    def archive_size(self) -> int:
        """Return total count of archived historical facts."""
        return len(self._archive_store)

    def scan_and_archive(
        self,
        records: Sequence[TemporalFactRecord],
        current_time: datetime | None = None,
    ) -> tuple[list[TemporalFactRecord], ExpirationScanResult]:
        """Audit records against current time and move expired entries to archive.

        Args:
            records: Active fact records under review.
            current_time: Optional evaluation timestamp (defaults to UTC now).

        Returns:
            Tuple of (retained_active_records, ExpirationScanResult).
        """
        now = self._ensure_utc(current_time or datetime.now(UTC))

        active_retained: list[TemporalFactRecord] = []
        archived_ids: list[str] = []
        expired_count = 0

        for r in records:
            to_time = self._ensure_utc(r.valid_to) if r.valid_to is not None else None

            # Fact has expired if current time has passed valid_to
            if to_time is not None and now > to_time:
                expired_count += 1
                archived_record = r.model_copy(deep=True)
                archived_record.status = FactTemporalState.ARCHIVED
                self._archive_store[archived_record.fact_id] = archived_record
                archived_ids.append(archived_record.fact_id)
            else:
                active_retained.append(r)

        result = ExpirationScanResult(
            scanned_count=len(records),
            expired_count=expired_count,
            archived_count=len(archived_ids),
            archived_fact_ids=archived_ids,
        )

        return active_retained, result

    def get_archived_facts(self) -> list[TemporalFactRecord]:
        """Retrieve all facts currently stored in the cold archive."""
        return list(self._archive_store.values())

    def get_archived_fact(self, fact_id: str) -> TemporalFactRecord | None:
        """Retrieve a specific archived fact by identifier."""
        return self._archive_store.get(fact_id)

    def restore_fact(self, fact_id: str) -> TemporalFactRecord | None:
        """Restore a previously archived fact back to ACTIVE state."""
        record = self._archive_store.pop(fact_id, None)
        if record is not None:
            record.status = FactTemporalState.ACTIVE
            return record
        return None

    def _ensure_utc(self, dt: datetime) -> datetime:
        """Normalize datetime to UTC timezone."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
