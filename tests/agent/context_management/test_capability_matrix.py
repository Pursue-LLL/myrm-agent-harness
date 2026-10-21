"""[INPUT]
- myrm_agent_harness.agent.context_management.capability_matrix: CapabilityDiscoveryEngine, ContextStateSnapshot

[OUTPUT]
- Unit tests verifying progressive heuristic recommendation, deduplication of mastered commands, and domain routing

[POS]
Harness framework layer test suite for Item 38 P0. Strictly under 160 lines. Zero `Any`.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.capability_matrix import (
    CapabilityDiscoveryEngine,
    ContextStateSnapshot,
)


def test_in_flight_running_task_recommends_concurrency_chips() -> None:
    context = ContextStateSnapshot(
        session_id="session_test_run",
        status="running",
        running_step_count=4,
        recent_tools=["web_search", "browser_click"],
        mastered_commands=[],
    )

    chips = CapabilityDiscoveryEngine.evaluate_recommendations(context, max_results=3)
    assert len(chips) == 3
    commands = [c.command for c in chips]
    assert "/btw" in commands
    assert "/bg" in commands
    assert "/steer" in commands

    # Verify highest priority is /btw
    assert chips[0].command == "/btw"
    assert "/btw " in chips[0].insert_prompt
    assert len(chips[0].label_zh) > 0
    assert len(chips[0].label_en) > 0


def test_active_coding_tools_recommends_pykernel() -> None:
    context = ContextStateSnapshot(
        session_id="session_code",
        status="idle",
        running_step_count=1,
        recent_tools=["bash", "python"],
        mastered_commands=[],
    )

    chips = CapabilityDiscoveryEngine.evaluate_recommendations(context, max_results=3)
    commands = [c.command for c in chips]
    assert "/pykernel" in commands
    pykernel_chip = next(c for c in chips if c.command == "/pykernel")
    assert "/pykernel start" in pykernel_chip.insert_prompt


def test_mastered_commands_are_filtered_out() -> None:
    context = ContextStateSnapshot(
        session_id="session_mastered",
        status="running",
        running_step_count=3,
        recent_tools=["python"],
        mastered_commands=["/btw", "/bg"],  # User already mastered /btw and /bg
    )

    chips = CapabilityDiscoveryEngine.evaluate_recommendations(context, max_results=5)
    commands = [c.command for c in chips]
    assert "/btw" not in commands
    assert "/bg" not in commands
    # Should still recommend /pykernel and /steer
    assert "/pykernel" in commands
    assert "/steer" in commands


def test_completed_multistep_task_recommends_sop_and_export() -> None:
    context = ContextStateSnapshot(
        session_id="session_finished",
        status="idle",
        running_step_count=6,
        recent_tools=["doc_writer"],
        mastered_commands=[],
    )

    chips = CapabilityDiscoveryEngine.evaluate_recommendations(context, max_results=3)
    commands = [c.command for c in chips]
    assert "/sop" in commands
    assert "/export" in commands
