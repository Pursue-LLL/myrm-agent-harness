"""Unit tests for Migration Progress and Diagnostic Reporter."""

import pytest

from myrm_agent_harness.observability.diagnostics import (
    MigrationDiagnosticReport,
    MigrationFailureDetail,
    MigrationPhase,
    MigrationProgressEvent,
    MigrationProgressReporter,
)


def test_migration_progress_reporter_lifecycle_and_events():
    """Test standard migration progress tracking and event streaming."""
    events: list[MigrationProgressEvent] = []

    def on_progress(event: MigrationProgressEvent) -> None:
        events.append(event)

    reporter = MigrationProgressReporter("migrate_v1_to_v2", on_progress=on_progress)
    assert reporter.current_phase == MigrationPhase.PREPARING

    # 1. Update phase
    reporter.set_phase(MigrationPhase.PARSING_JSONL, message="Reading JSONL history")
    assert reporter.current_phase == MigrationPhase.PARSING_JSONL

    # 2. Record success and update progress
    reporter.record_success(count=100)
    reporter.update_progress(current_items=100, total_items=200, status_message="Halfway done")

    # 3. Record failure
    reporter.record_failure(
        source_path="sessions.jsonl",
        error_message="Unexpected EOF in JSON record",
        line_number=101,
        raw_payload='{"id": "incomplete',
        actionable_hint="Skip corrupted line",
    )

    # 4. Finalize
    report = reporter.finalize(success=True)
    assert report.task_name == "migrate_v1_to_v2"
    assert report.success is True
    assert report.total_processed == 101  # 100 successes + 1 failure
    assert report.successful_items == 100
    assert report.failed_items_count == 1
    assert len(report.failures) == 1
    assert report.failures[0].line_number == 101
    assert "Unexpected EOF" in report.failures[0].error_message

    # Verify event stream
    assert len(events) >= 3
    assert events[-1].phase == MigrationPhase.COMPLETED


def test_migration_progress_event_percent():
    """Test percent_complete calculation on progress event."""
    event_with_total = MigrationProgressEvent(
        phase=MigrationPhase.MIGRATING_DB,
        task_name="db_upgrade",
        current_items=50,
        total_items=200,
    )
    assert event_with_total.percent_complete == 25.0

    event_no_total = MigrationProgressEvent(
        phase=MigrationPhase.MIGRATING_DB,
        task_name="db_upgrade",
        current_items=50,
        total_items=None,
    )
    assert event_no_total.percent_complete is None
