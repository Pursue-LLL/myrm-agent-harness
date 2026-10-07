"""Unit tests for memory reinforcement emphasis gate and mid-session dynamic skill attachment.

Validates priority elevation, attention decay protection countdowns, pinned directive immunity,
non-blocking runtime skill attachment/detachment, and combined prompt injection payload synthesis.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.memory_reinforce_emphasis_gate import (
    MemoryReinforceEmphasisGate,
)
from myrm_agent_harness.runtime.context.memory_reinforce_skill_attach_types import (
    ReinforcementPriorityKind,
)
from myrm_agent_harness.runtime.context.mid_session_skill_attachment_registry import (
    MidSessionSkillAttachmentRegistry,
)


@pytest.mark.asyncio
async def test_rule_registration_and_emphasis_elevation() -> None:
    """Validate registering normal rules and elevating to high attention priority."""
    gate = MemoryReinforceEmphasisGate(default_boost_turns=4)
    session_id = "sess_em_001"

    rule = gate.register_rule(
        session_id=session_id,
        rule_id="rule_strict_typing",
        content="Strictly forbid Any types; require explicit type annotations.",
        category="code_style",
    )
    assert rule.priority == ReinforcementPriorityKind.NORMAL
    assert rule.reinforce_count == 0
    assert rule.decay_suppression_rounds == 0

    # User clicks "Reinforce" (强调此规矩)
    boosted = gate.emphasize_rule(session_id, "rule_strict_typing")
    assert boosted.priority == ReinforcementPriorityKind.HIGH_ATTENTION_PRIORITY
    assert boosted.reinforce_count == 1
    assert boosted.decay_suppression_rounds == 4

    # Reinforce again to increment emphasis weight
    boosted2 = gate.emphasize_rule(session_id, "rule_strict_typing")
    assert boosted2.reinforce_count == 2

    prompt_block = gate.render_emphasis_prompt_block(session_id)
    assert "HIGH ATTENTION ACTIVE DIRECTIVES" in prompt_block
    assert "[code_style]" in prompt_block
    assert "(EMPHASIZED x2)" in prompt_block
    assert "Strictly forbid Any types" in prompt_block


@pytest.mark.asyncio
async def test_multi_turn_decay_and_graceful_reversion() -> None:
    """Ensure emphasized rules revert to normal after decay countdown expires."""
    gate = MemoryReinforceEmphasisGate(default_boost_turns=3)
    session_id = "sess_em_002"

    gate.register_rule(
        session_id=session_id,
        rule_id="rule_pep8",
        content="Always follow PEP8 naming conventions.",
        category="style",
    )
    gate.emphasize_rule(session_id, "rule_pep8", boost_turns=3)

    # Turn 1
    expired_1 = gate.step_turn_decay(session_id)
    assert len(expired_1) == 0
    assert len(gate.get_active_emphasis_rules(session_id)) == 1

    # Turn 2
    expired_2 = gate.step_turn_decay(session_id)
    assert len(expired_2) == 0
    assert len(gate.get_active_emphasis_rules(session_id)) == 1

    # Turn 3 - Countdown reaches 0, reverts to normal
    expired_3 = gate.step_turn_decay(session_id)
    assert expired_3 == ("rule_pep8",)
    assert len(gate.get_active_emphasis_rules(session_id)) == 0

    # Prompt block is now clean to avoid perpetual distraction
    prompt_block = gate.render_emphasis_prompt_block(session_id)
    assert prompt_block == ""


@pytest.mark.asyncio
async def test_pinned_directive_immunity_from_decay() -> None:
    """Verify that pinned directives remain active indefinitely through numerous turns."""
    gate = MemoryReinforceEmphasisGate()
    session_id = "sess_em_003"

    gate.register_rule(
        session_id=session_id,
        rule_id="rule_security_sandbox",
        content="Never execute unverified shell commands outside the container.",
        category="security",
    )
    gate.pin_directive(session_id, "rule_security_sandbox")

    # Simulate 15 turns
    for _ in range(15):
        expired = gate.step_turn_decay(session_id)
        assert len(expired) == 0

    active_rules = gate.get_active_emphasis_rules(session_id)
    assert len(active_rules) == 1
    assert active_rules[0].priority == ReinforcementPriorityKind.PINNED_SYSTEM_DIRECTIVE

    prompt_block = gate.render_emphasis_prompt_block(session_id)
    assert "(PINNED)" in prompt_block
    assert "Never execute unverified shell commands" in prompt_block


@pytest.mark.asyncio
async def test_mid_session_skill_hot_attachment_and_tools_space() -> None:
    """Validate dynamic non-blocking skill attachment, tool exposure, and detachment."""
    registry = MidSessionSkillAttachmentRegistry()
    session_id = "sess_em_004"

    # Mid-session attachment of Chart Generator skill
    skill_chart = registry.attach_skill(
        session_id=session_id,
        skill_id="skill_charts",
        skill_name="SVG Chart Renderer",
        description="Generates beautiful interactive SVG diagrams",
        tool_definitions=("render_svg", "export_png"),
        current_turn=5,
    )
    assert skill_chart.active is True
    assert skill_chart.attached_at_turn == 5

    # Mid-session attachment of SQL Query skill
    registry.attach_skill(
        session_id=session_id,
        skill_id="skill_sql",
        skill_name="Sandbox SQLite Query",
        description="Executes read-only SQL queries against project database",
        tool_definitions=("execute_sql",),
        current_turn=6,
    )

    tools = registry.get_available_tools(session_id)
    assert tools == ("execute_sql", "export_png", "render_svg")

    active_skills = registry.list_active_skills(session_id)
    assert len(active_skills) == 2

    # Detach chart skill
    detached = registry.detach_skill(session_id, "skill_charts")
    assert detached is True

    tools_after = registry.get_available_tools(session_id)
    assert tools_after == ("execute_sql",)
    assert len(registry.list_active_skills(session_id)) == 1


@pytest.mark.asyncio
async def test_runtime_context_injection_synthesis() -> None:
    """Verify combined prompt synthesis of reinforced rules and attached skills."""
    gate = MemoryReinforceEmphasisGate()
    registry = MidSessionSkillAttachmentRegistry()
    session_id = "sess_em_005"

    gate.register_rule(
        session_id=session_id,
        rule_id="rule_immutability",
        content="Prefer frozen dataclasses and immutable tuples.",
        category="architecture",
    )
    gate.emphasize_rule(session_id, "rule_immutability")

    registry.attach_skill(
        session_id=session_id,
        skill_id="skill_pdf_parser",
        skill_name="PDF Extraction Tool",
        description="Extracts textual paragraphs and tables from PDF documents",
        tool_definitions=("extract_pdf_pages",),
        current_turn=7,
    )

    payload = registry.synthesize_runtime_context_injection(session_id, gate=gate)
    assert payload.session_id == session_id
    assert payload.effective_rules_count == 1
    assert len(payload.active_attached_skills) == 1
    assert "Prefer frozen dataclasses" in payload.system_emphasis_block
    assert "DYNAMICALLY ATTACHED RUNTIME SKILLS" in payload.system_emphasis_block
    assert "PDF Extraction Tool" in payload.system_emphasis_block
    assert "extract_pdf_pages" in payload.system_emphasis_block
