"""Tests for delegation pause gate."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegation_pause_gate import (
    delegation_pause_status,
    is_delegation_paused,
    pause_delegation,
    resume_delegation,
)


def test_pause_resume_session_alias() -> None:
    pause_delegation("chat_alias_test")
    assert is_delegation_paused("alias_test") is True
    resume_delegation("alias_test")
    assert is_delegation_paused("chat_alias_test") is False

    session_id = "chat_pause_test"
    assert is_delegation_paused(session_id) is False
    assert pause_delegation(session_id) is True
    assert is_delegation_paused(session_id) is True
    status = delegation_pause_status(session_id)
    assert status["paused"] is True
    assert resume_delegation(session_id) is True
    assert is_delegation_paused(session_id) is False
