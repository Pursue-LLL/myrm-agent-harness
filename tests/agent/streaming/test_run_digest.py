from __future__ import annotations

from myrm_agent_harness.agent.streaming.run_digest import (
    RunDigestPhase,
    build_run_digest,
)


def test_build_run_digest_running_headline() -> None:
    digest = build_run_digest(
        chat_id="chat-1",
        progress_steps=[
            {"tool_name": "web_search_tool", "step_key": "s1", "status": "running"},
        ],
        phase=RunDigestPhase.RUNNING,
        elapsed_seconds=12,
    )
    assert digest.phase == RunDigestPhase.RUNNING
    assert digest.step_count == 1
    assert digest.current_tool == "web_search_tool"
    assert digest.headline == "Step 1: web_search_tool"
    assert digest.elapsed_seconds == 12
    assert len(digest.recent_steps) == 1
    assert digest.recent_steps[0].index == 1


def test_build_run_digest_waiting_approval() -> None:
    digest = build_run_digest(
        chat_id="chat-2",
        progress_steps=[],
        phase=RunDigestPhase.WAITING_APPROVAL,
        pending_approval_count=3,
    )
    assert digest.phase == RunDigestPhase.WAITING_APPROVAL
    assert "3" in digest.headline


def test_build_run_digest_recent_steps_window() -> None:
    steps = [
        {"tool_name": f"tool_{index}", "step_key": f"k{index}"}
        for index in range(7)
    ]
    digest = build_run_digest(
        chat_id="chat-3",
        progress_steps=steps,
        phase=RunDigestPhase.RUNNING,
        max_recent=3,
    )
    assert digest.step_count == 7
    assert len(digest.recent_steps) == 3
    assert digest.recent_steps[0].index == 5
    assert digest.recent_steps[-1].index == 7


def test_run_digest_to_dict_serializable() -> None:
    digest = build_run_digest(
        chat_id="chat-4",
        progress_steps=[{"tool_name": "bash", "step_key": "bash-1"}],
        phase=RunDigestPhase.COMPLETED,
    )
    payload = digest.to_dict()
    assert payload["chat_id"] == "chat-4"
    assert payload["phase"] == "completed"
    assert isinstance(payload["recent_steps"], list)


def test_build_run_digest_tool_label_fallbacks() -> None:
    digest = build_run_digest(
        chat_id="chat-5",
        progress_steps=[{"step_key": "only-key", "status": "running"}],
        phase=RunDigestPhase.RUNNING,
    )
    assert digest.current_tool == "only-key"
    assert digest.recent_steps[0].tool_name == "only-key"

    empty_label = build_run_digest(
        chat_id="chat-6",
        progress_steps=[{}],
        phase=RunDigestPhase.RUNNING,
    )
    assert empty_label.current_tool == "tool"


def test_build_run_digest_terminal_headlines() -> None:
    error_digest = build_run_digest(
        chat_id="chat-7",
        progress_steps=[],
        phase=RunDigestPhase.ERROR,
    )
    assert error_digest.headline == "Run failed"

    cancelled_digest = build_run_digest(
        chat_id="chat-8",
        progress_steps=[],
        phase=RunDigestPhase.CANCELLED,
    )
    assert cancelled_digest.headline == "Run cancelled"

    idle_digest = build_run_digest(
        chat_id="chat-9",
        progress_steps=[],
        phase=RunDigestPhase.IDLE,
    )
    assert idle_digest.headline == "Ready"
