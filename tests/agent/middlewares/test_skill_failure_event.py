from __future__ import annotations

from dataclasses import dataclass, field

from myrm_agent_harness.agent._skill_agent_context import add_loaded_skill, reset_loaded_skills
from myrm_agent_harness.agent.middlewares._session_context import set_approval_session
from myrm_agent_harness.agent.middlewares._skill_failure_tracking import (
    track_skill_execution as _track_skill_execution,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.runtime.events import SkillFailureEvent


@dataclass(slots=True)
class _FakeEventBus:
    events: list[SkillFailureEvent] = field(default_factory=list)

    def publish(self, event: object) -> None:
        if isinstance(event, SkillFailureEvent):
            self.events.append(event)


def test_tool_failure_publishes_skill_failure_event(monkeypatch) -> None:
    fake_bus = _FakeEventBus()
    monkeypatch.setattr(
        "myrm_agent_harness.runtime.events.get_event_bus",
        lambda: fake_bus,
    )

    reset_loaded_skills()
    add_loaded_skill(
        SkillMetadata(
            name="sales_report_skill",
            description="Download and summarize sales reports.",
            storage_skill_id="skill-1",
            storage_path="/skills/sales_report/SKILL.md",
            version="4",
        )
    )

    set_approval_session("chat-skill-failure")
    try:
        _track_skill_execution(
            "browser_interact_tool",
            tool_call_id="call-1",
            tool_args={"selector": "#download"},
            success=False,
            error_message="Timeout: selector #download was not found",
        )
    finally:
        set_approval_session("")
        reset_loaded_skills()

    assert len(fake_bus.events) == 1
    event = fake_bus.events[0]
    assert event.tool_name == "browser_interact_tool"
    assert event.tool_call_id == "call-1"
    assert event.tool_args_hash
    assert event.error_signature.startswith("browser_interact_tool:")
    assert event.session_id == "chat-skill-failure"
    assert event.candidates[0].skill_id == "skill-1"
    assert event.candidates[0].confidence == 1.0


def test_tool_failure_without_storage_skill_is_ignored(monkeypatch) -> None:
    fake_bus = _FakeEventBus()
    monkeypatch.setattr(
        "myrm_agent_harness.runtime.events.get_event_bus",
        lambda: fake_bus,
    )

    reset_loaded_skills()
    add_loaded_skill(
        SkillMetadata(
            name="ephemeral_mcp_skill",
            description="MCP generated skill.",
        )
    )

    _track_skill_execution(
        "bash_code_execute_tool",
        tool_call_id="call-2",
        tool_args={"command": "missing-binary"},
        success=False,
        error_message="command not found: missing-binary",
    )

    reset_loaded_skills()

    assert fake_bus.events == []


def test_policy_block_does_not_publish_skill_failure_event(monkeypatch) -> None:
    fake_bus = _FakeEventBus()
    monkeypatch.setattr(
        "myrm_agent_harness.runtime.events.get_event_bus",
        lambda: fake_bus,
    )

    reset_loaded_skills()
    add_loaded_skill(
        SkillMetadata(
            name="sales_report_skill",
            description="Download and summarize sales reports.",
            storage_skill_id="skill-1",
        )
    )

    try:
        _track_skill_execution(
            "browser_interact_tool",
            tool_call_id="call-policy",
            tool_args={},
            success=False,
            error_message="E-Stop active: all tool execution is suspended",
            error_category="estop",
        )
    finally:
        reset_loaded_skills()

    assert fake_bus.events == []


def test_loop_guard_failure_publishes_loop_metadata(monkeypatch) -> None:
    fake_bus = _FakeEventBus()
    monkeypatch.setattr(
        "myrm_agent_harness.runtime.events.get_event_bus",
        lambda: fake_bus,
    )

    reset_loaded_skills()
    add_loaded_skill(
        SkillMetadata(
            name="browser_checkout_skill",
            description="Complete checkout workflow.",
            storage_skill_id="skill-loop",
        )
    )

    set_approval_session("chat-loop")
    try:
        _track_skill_execution(
            "browser_interact_tool",
            tool_call_id="call-loop",
            tool_args={"selector": "#pay"},
            success=False,
            error_message="Error: Tool called repeatedly with identical arguments",
            error_category="loop_guard",
            loop_kind="repetition",
        )
    finally:
        set_approval_session("")
        reset_loaded_skills()

    assert len(fake_bus.events) == 1
    event = fake_bus.events[0]
    assert event.loop_kind == "repetition"
    assert event.session_id == "chat-loop"
