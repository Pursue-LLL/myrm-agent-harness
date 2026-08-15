from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from myrm_agent_harness.agent.middlewares._session_context import set_approval_session
from myrm_agent_harness.agent.middlewares.tooling._skill_failure_tracking import (
    track_skill_execution as _track_skill_execution,
)
from myrm_agent_harness.agent.skill_agent.context import (
    add_loaded_skill,
    reset_loaded_skills,
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


@pytest.mark.asyncio
async def test_success_records_evolution_when_single_skill(monkeypatch) -> None:
    """Single loaded storage skill + success → evolution.record_execution scheduled."""
    import asyncio

    reset_loaded_skills()
    add_loaded_skill(
        SkillMetadata(
            name="sales_report_skill",
            description="Download and summarize sales reports.",
            storage_skill_id="skill-1",
        )
    )

    recorded: list[dict[str, object]] = []

    async def _record(self, **kwargs):
        recorded.append(kwargs)

    evolution = type("Evo", (), {"record_execution": _record})()
    monkeypatch.setattr(
        "myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration",
        lambda: evolution,
    )
    try:
        _track_skill_execution(
            "browser_interact_tool",
            tool_call_id="call-ok",
            tool_args={},
            success=True,
            error_message="",
        )
        await asyncio.sleep(0)
    finally:
        reset_loaded_skills()
    assert len(recorded) == 1
    assert recorded[0]["success"] is True


def test_success_multiple_skills_skips_evolution(monkeypatch) -> None:
    """Multiple loaded storage skills → no evolution record (ambiguous owner)."""
    reset_loaded_skills()
    add_loaded_skill(
        SkillMetadata(name="a", description="a", storage_skill_id="s1", version="1"),
    )
    add_loaded_skill(
        SkillMetadata(name="b", description="b", storage_skill_id="s2", version="2"),
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration",
        lambda: type("Evo", (), {"record_execution": lambda **kw: None})(),
    )
    try:
        _track_skill_execution(
            "tool",
            tool_call_id="c",
            tool_args={},
            success=True,
            error_message="",
        )
    finally:
        reset_loaded_skills()


def test_success_no_evolution_skips(monkeypatch) -> None:
    """Single skill but no evolution integration → no-op."""
    reset_loaded_skills()
    add_loaded_skill(
        SkillMetadata(name="a", description="a", storage_skill_id="s1", version="1"),
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration",
        lambda: None,
    )
    try:
        _track_skill_execution(
            "tool",
            tool_call_id="c",
            tool_args={},
            success=True,
            error_message="",
        )
    finally:
        reset_loaded_skills()


def test_multiple_storage_skills_candidates_have_confidence(monkeypatch) -> None:
    """Multiple storage skills → latest gets 0.65 confidence, others 0.25."""
    fake_bus = _FakeEventBus()
    monkeypatch.setattr(
        "myrm_agent_harness.runtime.events.get_event_bus",
        lambda: fake_bus,
    )
    reset_loaded_skills()
    add_loaded_skill(
        SkillMetadata(name="a", description="a", storage_skill_id="s1", version="1"),
    )
    add_loaded_skill(
        SkillMetadata(name="b", description="b", storage_skill_id="s2", version="2"),
    )
    try:
        _track_skill_execution(
            "tool",
            tool_call_id="c",
            tool_args={},
            success=False,
            error_message="boom",
        )
    finally:
        reset_loaded_skills()
    assert len(fake_bus.events) == 1
    confidences = {c.skill_id: c.confidence for c in fake_bus.events[0].candidates}
    assert confidences == {"s1": 0.25, "s2": 0.65}


def test_sanitize_error_message_redacts_long_tokens(monkeypatch) -> None:
    """Long secretish tokens are redacted and content truncated to 1000 chars."""
    from myrm_agent_harness.agent.middlewares.tooling._skill_failure_tracking import (
        _sanitize_error_message,
    )

    secret = "sk-" + "a" * 40
    result = _sanitize_error_message(f"first line\nsecond {secret}\n{secret}")
    assert "a" * 40 not in result
    assert "<redacted>" in result


def test_hash_tool_args_covers_unserializable(monkeypatch) -> None:
    from myrm_agent_harness.agent.middlewares.tooling._skill_failure_tracking import (
        _hash_tool_args,
    )

    assert _hash_tool_args({"a": 1})
    assert _hash_tool_args({"x": object()})
