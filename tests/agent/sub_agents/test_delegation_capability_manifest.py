"""Tests for DelegationCapabilityManifest and related type helpers."""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.types import (
    AgentHandoverState,
    CouncilOpinion,
    CouncilResult,
    DELEGATION_CAPABILITY_MANIFEST,
    DelegationCapabilityManifest,
    SubAgentResult,
    SubAgentStatus,
)


def test_default_manifest_blocks_hitl_and_delegation_tools() -> None:
    manifest = DelegationCapabilityManifest.default()
    blocked = manifest.leaf_blocked_tools

    assert "ask_question_tool" in blocked
    assert "delegate_task_tool" in blocked
    assert "spawn_subagent_tool" in blocked
    assert manifest.orchestrator_child_tools == (
        "delegate_task_tool",
        "subagent_control_tool",
        "send_teammate_message_tool",
    )


def test_module_manifest_matches_default_factory() -> None:
    assert DELEGATION_CAPABILITY_MANIFEST == DelegationCapabilityManifest.default()


def test_sub_agent_result_to_dict_includes_optional_fields() -> None:
    handover = AgentHandoverState(
        task_completed=["done"],
        pending_todos=["todo"],
        risks_or_notes=["risk"],
        relevant_files=["file.py"],
    )
    result = SubAgentResult(
        success=True,
        task_id="task-1",
        agent_type="researcher",
        result="ok",
        status=SubAgentStatus.COMPLETED,
        duration_seconds=1.5,
        completed_at=100.0,
        trace_id="trace-1",
        error="",
        token_usage=None,
        payload={"key": "value"},
        checkpoint_data={"ck": 1},
        handover_state=handover,
        accumulated_duration_seconds=2.0,
        still_running=True,
    )

    data = result.to_dict()

    assert data["still_running"] is True
    assert "completed_at" not in data
    assert data["trace_id"] == "trace-1"
    assert data["payload"] == {"key": "value"}
    assert data["handover_state"] == handover.to_dict()
    assert data["accumulated_duration_seconds"] == 2.0


def test_agent_handover_state_from_dict_filters_non_strings() -> None:
    state = AgentHandoverState.from_dict(
        {
            "task_completed": ["a", 1],
            "pending_todos": "invalid",
            "risks_or_notes": ["note"],
            "relevant_files": [],
        }
    )

    assert state.task_completed == ["a"]
    assert state.pending_todos == []
    assert state.risks_or_notes == ["note"]


def test_council_result_to_dict_includes_error_when_present() -> None:
    opinion = CouncilOpinion(
        expert_id="expert-1",
        agent_type="analyst",
        round_num=1,
        content="analysis",
        success=True,
    )
    council = CouncilResult(
        success=False,
        synthesis="partial",
        opinions=(opinion,),
        error="failed round",
    )

    data = council.to_dict()

    assert data["error"] == "failed round"
    assert data["opinions"][0]["expert_id"] == "expert-1"
