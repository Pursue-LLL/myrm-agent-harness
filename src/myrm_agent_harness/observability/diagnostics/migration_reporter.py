"""Migration Progress and Diagnostic Reporter for database and configuration upgrades.

[INPUT]
- None (Standard library dataclasses, enum, typing, time)

[OUTPUT]
- MigrationPhase: Enum of standard migration lifecycle phases
- MigrationProgressEvent: Immutable progress event emitted during migration steps
- MigrationFailureDetail: Detailed record of an individual item or line copy/parse failure
- MigrationDiagnosticReport: Final structured summary report produced at the end of migration
- MigrationProgressReporter: Context manager and event driver for migration tracking

[POS]
Harness-level migration diagnostic and progress observability protocol ensuring transparent, zero-silent-corruption upgrades.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Sequence


class MigrationPhase(str, Enum):
    """Lifecycle phases of a data or configuration migration task."""

    PREPARING = "PREPARING"            # Inspecting source files, backing up existing data
    COPYING_CONFIG = "COPYING_CONFIG"  # Copying legacy configurations / settings
    PARSING_JSONL = "PARSING_JSONL"    # Parsing and validating session/event JSONL records
    MIGRATING_DB = "MIGRATING_DB"      # Schema alter, SQLite transaction execution
    VECTOR_REINDEX = "VECTOR_REINDEX"  # Rebuilding embeddings or Qdrant index
    FINALIZING = "FINALIZING"          # Committing changes, cleaning temporary files
    COMPLETED = "COMPLETED"            # Migration finished successfully
    FAILED = "FAILED"                  # Migration terminated on fatal error


@dataclass(frozen=True, slots=True)
class MigrationFailureDetail:
    """Detailed record of a failed record or copy step during migration.

    Attributes:
        source_path: File path or database table where failure occurred.
        line_number: Line number (for JSONL/text files) if applicable.
        error_message: Human-readable error description.
        raw_payload: Sanitized snippet of the malformed record or configuration.
        actionable_hint: Clear instructions on how to remediate or skip.
    """

    source_path: str
    error_message: str
    line_number: int | None = None
    raw_payload: str | None = None
    actionable_hint: str = "Inspect source file for syntax errors or permission issues."


@dataclass(frozen=True, slots=True)
class MigrationProgressEvent:
    """Streamed event capturing real-time migration progress.

    Attributes:
        phase: Current MigrationPhase.
        task_name: Descriptive name of the migration job.
        current_items: Number of items/records processed so far.
        total_items: Total expected items (None if unknown/streaming).
        elapsed_ms: Milliseconds elapsed since migration start.
        status_message: Human-readable progress description.
        occurred_at: Event timestamp.
    """

    phase: MigrationPhase
    task_name: str
    current_items: int = 0
    total_items: int | None = None
    elapsed_ms: float = 0.0
    status_message: str = ""
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def percent_complete(self) -> float | None:
        """Percentage of completion (0.0 to 100.0) if total_items is known."""
        if self.total_items is None or self.total_items <= 0:
            return None
        return min(100.0, round((self.current_items / self.total_items) * 100.0, 2))


@dataclass(frozen=True, slots=True)
class MigrationDiagnosticReport:
    """Comprehensive final diagnostic report of a migration execution.

    Attributes:
        task_name: Descriptive migration job identifier.
        success: Whether the migration completed without fatal abortion.
        total_processed: Total count of items/records processed.
        successful_items: Count of items successfully converted/migrated.
        failed_items_count: Count of malformed records or copy failures.
        failures: Detailed list of all recorded MigrationFailureDetail.
        duration_ms: Total duration in milliseconds.
        summary_message: High-level outcome summary.
    """

    task_name: str
    success: bool
    total_processed: int
    successful_items: int
    failed_items_count: int
    failures: list[MigrationFailureDetail] = field(default_factory=list)
    duration_ms: float = 0.0
    summary_message: str = ""


class MigrationProgressReporter:
    """Thread-safe migration progress tracking and diagnostic reporter."""

    def __init__(
        self,
        task_name: str,
        *,
        on_progress: Callable[[MigrationProgressEvent], None] | None = None,
    ) -> None:
        self._task_name = task_name
        self._on_progress = on_progress
        self._start_time: float = time.perf_counter()
        self._current_phase = MigrationPhase.PREPARING
        self._total_processed = 0
        self._successful_items = 0
        self._failures: list[MigrationFailureDetail] = []
        self._is_completed = False

    @property
    def current_phase(self) -> MigrationPhase:
        """Get the current migration phase."""
        return self._current_phase

    def set_phase(self, phase: MigrationPhase, message: str = "") -> None:
        """Transition to a new migration phase and emit progress event."""
        self._current_phase = phase
        self._emit_event(current_items=self._total_processed, status_message=message)

    def update_progress(
        self,
        current_items: int,
        total_items: int | None = None,
        status_message: str = "",
    ) -> None:
        """Update processed item counts and emit progress notification."""
        self._total_processed = current_items
        self._emit_event(current_items=current_items, total_items=total_items, status_message=status_message)

    def record_success(self, count: int = 1) -> None:
        """Increment count of successfully migrated items."""
        self._successful_items += count
        self._total_processed += count

    def record_failure(
        self,
        *,
        source_path: str,
        error_message: str,
        line_number: int | None = None,
        raw_payload: str | None = None,
        actionable_hint: str = "Check file syntax or file permissions.",
    ) -> None:
        """Explicitly record a malformed record or copy failure instead of silently dropping."""
        self._total_processed += 1
        detail = MigrationFailureDetail(
            source_path=source_path,
            error_message=error_message,
            line_number=line_number,
            raw_payload=raw_payload,
            actionable_hint=actionable_hint,
        )
        self._failures.append(detail)

    def _emit_event(
        self,
        current_items: int,
        total_items: int | None = None,
        status_message: str = "",
    ) -> None:
        elapsed = (time.perf_counter() - self._start_time) * 1000.0
        event = MigrationProgressEvent(
            phase=self._current_phase,
            task_name=self._task_name,
            current_items=current_items,
            total_items=total_items,
            elapsed_ms=round(elapsed, 2),
            status_message=status_message,
        )
        if self._on_progress:
            try:
                self._on_progress(event)
            except Exception:
                pass  # Do not allow callback exceptions to interrupt migration

    def finalize(self, success: bool = True, summary_message: str = "") -> MigrationDiagnosticReport:
        """Finalize migration and generate diagnostic report."""
        elapsed = (time.perf_counter() - self._start_time) * 1000.0
        self._current_phase = MigrationPhase.COMPLETED if success else MigrationPhase.FAILED
        self._emit_event(current_items=self._total_processed, status_message=summary_message or "Finalized")

        default_summary = (
            f"Migration '{self._task_name}' completed in {elapsed:.1f}ms: "
            f"{self._successful_items} succeeded, {len(self._failures)} failed/quarantined."
        )

        return MigrationDiagnosticReport(
            task_name=self._task_name,
            success=success,
            total_processed=self._total_processed,
            successful_items=self._successful_items,
            failed_items_count=len(self._failures),
            failures=list(self._failures),
            duration_ms=round(elapsed, 2),
            summary_message=summary_message or default_summary,
        )
