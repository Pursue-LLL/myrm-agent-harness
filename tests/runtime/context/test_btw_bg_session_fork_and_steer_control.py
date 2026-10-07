"""Unit tests for background session forks (/bg, /btw) and in-flight steer control (/steer).

Verifies:
1. Non-blocking isolated background session creation (/bg) and result pipe-back.
2. Context snapshot exploration (/btw) preserving main session purity.
3. In-flight human steering interception at step checkpoints with priority sorting.
4. Session isolation and lifecycle cancellation handling.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.in_flight_steer_controller import (
    InFlightSteerController,
)
from myrm_agent_harness.runtime.context.session_fork_manager import (
    SessionForkManager,
)
from myrm_agent_harness.runtime.context.session_fork_steer_types import (
    ForkCommandKind,
    ForkSessionState,
)


def test_bg_isolated_fork_lifecycle_and_pipe_back() -> None:
    manager = SessionForkManager()
    main_session_id = "sess_main_01"

    # Step 1: User issues /bg command while main task is executing
    fork = manager.create_bg_fork(
        parent_session_id=main_session_id,
        prompt="Search for Python 3.13 free-threaded performance reports.",
    )
    assert fork.kind == ForkCommandKind.BG
    assert fork.parent_session_id == main_session_id
    assert fork.state == ForkSessionState.STAGED
    assert fork.snapshot_context is None

    # Step 2: Query active background tasks for main session
    active = manager.get_active_forks(main_session_id)
    assert len(active) == 1
    assert active[0].fork_id == fork.fork_id

    # Step 3: Transition to RUNNING
    manager.update_fork_state(fork.fork_id, ForkSessionState.RUNNING)
    assert manager.get_fork(fork.fork_id).state == ForkSessionState.RUNNING  # type: ignore[union-attr]

    # Step 4: Complete task and verify automatic pipe-back staging
    completed = manager.update_fork_state(
        fork_id=fork.fork_id,
        state=ForkSessionState.COMPLETED,
        result_summary="Found 3 PEPs and 2 benchmark graphs.",
        artifacts=["report_summary.md", "benchmarks.csv"],
    )
    assert completed.state == ForkSessionState.COMPLETED
    assert completed.completed_at_ms is not None

    # Step 5: Main session drains pipe-back results
    piped = manager.drain_pipe_back_events(main_session_id)
    assert len(piped) == 1
    result = piped[0]
    assert result.fork_id == fork.fork_id
    assert result.kind == ForkCommandKind.BG
    assert result.status == ForkSessionState.COMPLETED
    assert "benchmark graphs" in result.output_content
    assert "report_summary.md" in result.artifacts

    # Ensure queue is drained (no double-processing)
    assert len(manager.drain_pipe_back_events(main_session_id)) == 0


def test_btw_context_snapshot_forking_preserves_main_purity() -> None:
    manager = SessionForkManager()
    main_session_id = "sess_main_02"
    parent_context = "System: Database is SQLite.\nUser: Refactoring connection pooling."

    # User issues /btw command to explore hypothetical architecture
    fork = manager.create_btw_fork(
        parent_session_id=main_session_id,
        prompt="What if we switch to DuckDB for analytics?",
        snapshot_context=parent_context,
    )
    assert fork.kind == ForkCommandKind.BTW
    assert fork.snapshot_context == parent_context

    # Simulate exploration finishing
    manager.update_fork_state(
        fork_id=fork.fork_id,
        state=ForkSessionState.COMPLETED,
        result_summary="DuckDB would speed up OLAP queries by 4x but requires schema migration.",
    )

    piped = manager.drain_pipe_back_events(main_session_id)
    assert len(piped) == 1
    assert piped[0].kind == ForkCommandKind.BTW
    assert "DuckDB" in piped[0].output_content


def test_in_flight_steer_checkpoint_interception_and_formatting() -> None:
    controller = InFlightSteerController()
    session_id = "sess_heavy_task"

    assert not controller.has_pending_steer(session_id)
    assert controller.pending_count(session_id) == 0

    # User submits steering directive 1
    s1 = controller.submit_steer(
        session_id=session_id,
        instruction="Focus exclusively on src/runtime/ and skip tests for now.",
        priority_weight=10,
    )
    assert s1.consumed_at_ms is None

    # User submits higher priority urgent steering directive 2
    controller.submit_steer(
        session_id=session_id,
        instruction="CRITICAL: Do not drop existing tables under any circumstance!",
        priority_weight=20,
    )

    assert controller.has_pending_steer(session_id)
    assert controller.pending_count(session_id) == 2

    # Agent loop reaches step checkpoint -> consumes all pending directives
    consumed = controller.consume_pending_steers(session_id)
    assert len(consumed) == 2

    # Higher priority directive (weight 20) must come first
    assert consumed[0].priority_weight == 20
    assert "Do not drop existing tables" in consumed[0].instruction
    assert consumed[0].consumed_at_ms is not None

    assert consumed[1].priority_weight == 10
    assert "Focus exclusively" in consumed[1].instruction

    # Checkpoint queue must now be empty
    assert not controller.has_pending_steer(session_id)
    assert len(controller.consume_pending_steers(session_id)) == 0

    # Format human steering prompt block
    prompt_block = controller.format_steer_prompt_block(consumed)
    assert "=== HUMAN STEERING INTERVENTION ===" in prompt_block
    assert "1. [Priority: 20] CRITICAL: Do not drop existing tables" in prompt_block
    assert "2. [Priority: 10] Focus exclusively on src/runtime/" in prompt_block
    assert "=== END STEERING INTERVENTION ===" in prompt_block


def test_fork_cancellation_and_session_isolation() -> None:
    manager = SessionForkManager()
    session_a = "sess_a"
    session_b = "sess_b"

    fork_a = manager.create_bg_fork(session_a, "Task A")
    fork_b = manager.create_bg_fork(session_b, "Task B")

    # Complete fork_b
    manager.update_fork_state(fork_b.fork_id, ForkSessionState.COMPLETED, "Done B")

    # Drain session_a should yield nothing from session_b
    assert len(manager.drain_pipe_back_events(session_a)) == 0

    # Cancel fork_a
    cancelled = manager.cancel_fork(fork_a.fork_id)
    assert cancelled is not None
    assert cancelled.state == ForkSessionState.CANCELLED

    # Cancelled task does not produce pipe-back output
    assert len(manager.drain_pipe_back_events(session_a)) == 0

    # Empty steer instruction raises ValueError
    steer_ctrl = InFlightSteerController()
    with pytest.raises(ValueError):
        steer_ctrl.submit_steer(session_a, "   ")
