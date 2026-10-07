from __future__ import annotations

from myrm_agent_harness.agent.streaming import (
    GracefulTurnInterrupter,
    InterruptionSignalKind,
    PartialArtifactFlushPipeline,
)


def test_graceful_preemption_at_step_4_of_10() -> None:
    """Simulate a 10-step turn gracefully interrupted at step 4 by a preemptive user message."""
    interrupter = GracefulTurnInterrupter(session_id="session_test_42", turn_index=1)
    pipeline = PartialArtifactFlushPipeline()

    executed_steps: list[int] = []

    # Run steps 1 to 10
    total_steps = 10
    for step_i in range(1, total_steps + 1):
        # Step work executes
        executed_steps.append(step_i)
        tool_desc = f"Tool step {step_i}: ran command for task component {step_i}"

        # In-flight partial code generation at step 2 and step 4
        if step_i == 2:
            pipeline.register_partial_artifact(
                name="auth_service.py",
                artifact_type="python_file",
                content="def authenticate(token: str) -> bool:\n    return True\n",
            )
        elif step_i == 4:
            pipeline.register_partial_artifact(
                name="test_auth.py",
                artifact_type="test_file",
                content="def test_auth():\n    assert authenticate('valid')\n",
            )

        # User types a preemptive message while step 4 is concluding
        if step_i == 4:
            interrupter.request_graceful_interruption(
                signal_kind=InterruptionSignalKind.GRACEFUL_PREEMPTION,
                preempting_message="Stop, please switch to OAuth2 bearer token flow instead of standard token.",
            )

        # Clean breakpoint check after atomic step completes
        should_stop = interrupter.check_breakpoint_and_interrupt(
            current_step=step_i,
            total_steps=total_steps,
            executed_tool_summary=tool_desc,
        )

        if should_stop:
            break

    # 1. Verify execution safely halted exactly at step 4
    assert executed_steps == [1, 2, 3, 4]
    assert interrupter.is_interrupted is True

    # 2. Flush partial artifacts safely
    flushed_artifacts = pipeline.flush_partial_artifacts()
    assert len(flushed_artifacts) == 2
    assert flushed_artifacts[0].name == "auth_service.py"
    assert flushed_artifacts[1].name == "test_auth.py"
    assert flushed_artifacts[0].is_partially_flushed is True

    # 3. Generate diagnostic interruption report
    report = interrupter.generate_report(flushed_artifacts)
    assert report.session_id == "session_test_42"
    assert report.turn_index == 1
    assert report.step_index_interrupted == 4
    assert report.total_planned_steps == 10
    assert report.signal_kind == InterruptionSignalKind.GRACEFUL_PREEMPTION
    assert "OAuth2 bearer token" in (report.preempting_user_message or "")
    assert len(report.executed_tool_summaries) == 4

    # 4. Context stitching for subsequent turn
    stitched = pipeline.stitch_preempted_context(report)
    xml = stitched.rendered_context_xml
    assert "<system_turn_interruption_handoff>" in xml
    assert "[STATUS]: Prior turn 1 was gracefully interrupted at step 4/10" in xml
    assert "[PREEMPTING_USER_INPUT]:\nStop, please switch to OAuth2 bearer token flow" in xml
    assert "auth_service.py" in xml
    assert "test_auth.py" in xml
    assert "[CONTINUATION_DIRECTIVE]:" in xml
    assert "Do not re-execute the preserved tools" in xml
    assert "Turn 1 interrupted at step 4 with 2 preserved artifacts" in stitched.summary_digest


def test_normal_uninterrupted_execution_and_reset() -> None:
    """Test full completion when no interruption occurs, followed by turn reset."""
    interrupter = GracefulTurnInterrupter(session_id="session_normal", turn_index=2)
    pipeline = PartialArtifactFlushPipeline()

    executed_count = 0
    for step_i in range(1, 6):
        executed_count += 1
        should_stop = interrupter.check_breakpoint_and_interrupt(
            current_step=step_i,
            total_steps=5,
            executed_tool_summary=f"step_{step_i}",
        )
        assert should_stop is False

    assert executed_count == 5
    assert interrupter.is_interrupted is False
    assert len(pipeline.flush_partial_artifacts()) == 0

    # Reset for next turn
    interrupter.reset_for_next_turn()
    assert interrupter.turn_index == 3
    assert interrupter.is_interrupted is False
    assert interrupter.is_interruption_requested is False
