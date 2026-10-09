"""Comprehensive tests for TerminalMissingSilentEndServerReconcileSuite.

[INPUT]
- silent_end_reconcile package contracts and implementations.

[OUTPUT]
- Deterministic verification of SSE stream terminal event monitoring, silent end detection,
  server run reservation querying, and unblocked loading state settlement.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_silent_end_reconcile_suite.py
"""

import pytest

from myrm_agent_harness.agent.context_management.silent_end_reconcile import (
    ReconcileOutcome,
    ReconcileVerdict,
    ServerRunReservation,
    ServerRuntimeVerifier,
    SilentEndReconcileConfig,
    SilentEndTicket,
    StreamRunStatus,
    StreamTerminalWatchdog,
    TerminalEventKind,
    TerminalMissingSilentEndServerReconcileSuite,
)


def test_stream_terminal_watchdog_clean_completion() -> None:
    """Verifies that streams terminating with legitimate terminal events are marked clean without tickets."""
    watchdog = StreamTerminalWatchdog()
    session_id = "sess-alpha-001"
    run_id = "run-001"

    watchdog.register_stream_start(session_id, run_id)
    watchdog.record_chunk_event(session_id, run_id, "delta_text", event_id="chunk-1")
    watchdog.record_chunk_event(session_id, run_id, "delta_text", event_id="chunk-2")
    watchdog.record_chunk_event(session_id, run_id, TerminalEventKind.MESSAGE_END.value, event_id="chunk-3")

    assert watchdog.has_terminal_received(session_id, run_id) is True

    # Transport EOF after terminal event -> returns None (clean)
    ticket = watchdog.on_stream_transport_completed(session_id, run_id, "EOF")
    assert ticket is None


def test_stream_terminal_watchdog_silent_end_detection() -> None:
    """Verifies that stream transport EOF without terminal envelopes issues a SilentEndTicket."""
    watchdog = StreamTerminalWatchdog()
    session_id = "sess-beta-002"
    run_id = "run-002"

    watchdog.register_stream_start(session_id, run_id)
    watchdog.record_chunk_event(session_id, run_id, "delta_text", event_id="chunk-1")
    watchdog.record_chunk_event(session_id, run_id, "delta_text", event_id="chunk-2")

    assert watchdog.has_terminal_received(session_id, run_id) is False

    ticket = watchdog.on_stream_transport_completed(
        session_id=session_id,
        run_id=run_id,
        transport_reason="Connection reset by peer unexpectedly",
    )

    assert ticket is not None
    assert ticket.session_id == session_id
    assert ticket.run_id == run_id
    assert ticket.total_chunks_received == 2
    assert ticket.last_event_id == "chunk-2"
    assert "Connection reset" in ticket.raw_interruption_reason


def test_server_runtime_verifier_outcomes() -> None:
    """Verifies reconciliation decisions across completed, active, and expired server states."""
    verifier = ServerRuntimeVerifier()
    ticket = SilentEndTicket(
        session_id="sess-gamma",
        run_id="run-777",
        last_event_id="e-9",
        total_chunks_received=5,
        detected_at_epoch=1000.0,
        raw_interruption_reason="Silent EOF",
    )

    # 1. Server reservation not found -> abort and unblock UI
    outcome_missing = verifier.reconcile_silent_end(ticket)
    assert outcome_missing.verdict == ReconcileVerdict.UNRECOVERABLE_ABORT
    assert outcome_missing.should_clear_loading_state is True

    # 2. Server confirms completed archived
    verifier.register_server_reservation(
        ServerRunReservation(
            session_id="sess-gamma",
            run_id="run-777",
            status=StreamRunStatus.COMPLETED_ARCHIVED,
            final_output_digest="sha256:abc12345",
        )
    )
    outcome_completed = verifier.reconcile_silent_end(ticket)
    assert outcome_completed.verdict == ReconcileVerdict.CONFIRMED_TERMINATED
    assert outcome_completed.should_clear_loading_state is True
    assert "completed successfully" in outcome_completed.recovery_guidance

    # 3. Server confirms run is still actively processing in background
    verifier.register_server_reservation(
        ServerRunReservation(
            session_id="sess-gamma",
            run_id="run-777",
            status=StreamRunStatus.ACTIVE_PROCESSING,
        )
    )
    outcome_active = verifier.reconcile_silent_end(ticket)
    assert outcome_active.verdict == ReconcileVerdict.STILL_RUNNING_RESUME
    assert outcome_active.should_clear_loading_state is False
    assert "actively executing" in outcome_active.recovery_guidance

    # 4. Server confirms failed aborted
    verifier.register_server_reservation(
        ServerRunReservation(
            session_id="sess-gamma",
            run_id="run-777",
            status=StreamRunStatus.FAILED_ABORTED,
            error_diagnostic="Out of context tokens",
        )
    )
    outcome_failed = verifier.reconcile_silent_end(ticket)
    assert outcome_failed.verdict == ReconcileVerdict.CONFIRMED_TERMINATED
    assert outcome_failed.should_clear_loading_state is True
    assert "Out of context tokens" in outcome_failed.recovery_guidance


def test_terminal_missing_silent_end_suite_facade_end_to_end() -> None:
    """Verifies end-to-end operation of the master facade across normal and silent end lifecycles."""
    suite = TerminalMissingSilentEndServerReconcileSuite()

    # Case 1: Clean stream lifecycle
    suite.start_stream_turn("sess-1", "run-clean")
    suite.ingest_stream_event("sess-1", "run-clean", "text_delta")
    suite.ingest_stream_event("sess-1", "run-clean", TerminalEventKind.RUN_FINISHED.value)
    clean_outcome = suite.conclude_stream_transport("sess-1", "run-clean")
    assert clean_outcome is None
    assert suite.is_turn_terminal_delivered("sess-1", "run-clean") is False  # reset after completion

    # Case 2: Silent end with server confirming completed state
    suite.start_stream_turn("sess-2", "run-silent-done")
    suite.ingest_stream_event("sess-2", "run-silent-done", "partial_thought")
    suite.register_server_reservation(
        session_id="sess-2",
        run_id="run-silent-done",
        status=StreamRunStatus.COMPLETED_ARCHIVED,
        final_output_digest="digest-456",
    )
    silent_outcome = suite.conclude_stream_transport("sess-2", "run-silent-done", "HTTP connection closed abruptly")
    assert silent_outcome is not None
    assert silent_outcome.verdict == ReconcileVerdict.CONFIRMED_TERMINATED
    assert silent_outcome.should_clear_loading_state is True

    # Case 3: Silent end with server still executing in background
    suite.start_stream_turn("sess-3", "run-silent-busy")
    suite.ingest_stream_event("sess-3", "run-silent-busy", "token_stream")
    suite.register_server_reservation(
        session_id="sess-3",
        run_id="run-silent-busy",
        status=StreamRunStatus.ACTIVE_PROCESSING,
    )
    busy_outcome = suite.conclude_stream_transport("sess-3", "run-silent-busy", "Gateway timeout")
    assert busy_outcome is not None
    assert busy_outcome.verdict == ReconcileVerdict.STILL_RUNNING_RESUME
    assert busy_outcome.should_clear_loading_state is False
