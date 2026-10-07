"""Unit tests for Active Skill Context Compaction Immunity and Re-Anchor Suite (Item 213).

[INPUT]
- ActiveSkillImmunityEngine, ActiveSkillSpec, SkillImmunityConfig.
- Simulated multi-turn compacted context frames.

[OUTPUT]
- Deterministic verification of compaction immunity shielding, post-compaction re-anchoring,
- and prompt cache alignment.

[POS]
- Verifies zero skill SOP dilution across compactions and deterministic prompt caching.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.skill_immunity import (
    ActiveSkillImmunityEngine,
    ActiveSkillSpec,
    ReAnchorAnchorPosition,
    SkillImmunityConfig,
    SkillImmunityScope,
)


def test_active_skill_registration_lifecycle() -> None:
    """Verifies registration, deterministic retrieval, unregistration, and clearing."""
    engine = ActiveSkillImmunityEngine()
    session_id = "session_test_001"

    skill_b = ActiveSkillSpec(
        skill_id="skill_b",
        name="Skill Beta",
        sop_rules=["Beta rule 1", "Beta rule 2"],
        scope=SkillImmunityScope.IMMUNE_CORE,
    )
    skill_a = ActiveSkillSpec(
        skill_id="skill_a",
        name="Skill Alpha",
        sop_rules=["Alpha rule 1"],
        scope=SkillImmunityScope.IMMUNE_CORE,
    )

    # Register in reverse order
    engine.register_skill(session_id, skill_b)
    engine.register_skill(session_id, skill_a)

    # Verify deterministic sorting (a before b)
    active = engine.get_active_skills(session_id)
    assert len(active) == 2
    assert active[0].skill_id == "skill_a"
    assert active[1].skill_id == "skill_b"

    # Unregister one skill
    assert engine.unregister_skill(session_id, "skill_b") is True
    assert engine.unregister_skill(session_id, "non_existent") is False
    assert len(engine.get_active_skills(session_id)) == 1

    # Clear session
    engine.clear_session(session_id)
    assert len(engine.get_active_skills(session_id)) == 0


def test_compaction_immunity_partitioning() -> None:
    """Verifies that immune skill SOP messages are shielded from lossy summarization."""
    engine = ActiveSkillImmunityEngine()
    session_id = "session_test_002"

    skill = ActiveSkillSpec(
        skill_id="code_review_sop",
        name="Code Review SOP",
        sop_rules=["Always run static checks", "Enforce 0 Any"],
        scope=SkillImmunityScope.IMMUNE_CORE,
    )
    engine.register_skill(session_id, skill)

    messages: list[dict[str, object]] = [
        {"role": "system", "content": "You are a helpful coding assistant."},
        {
            "role": "system",
            "content": "Special SOP message",
            "metadata": {"skill_id": "code_review_sop"},
        },
        {"role": "user", "content": "Please review this pull request."},
        {
            "role": "assistant",
            "content": "Here is some general banter...",
        },
        {
            "role": "system",
            "content": "Tagged immune node",
            "metadata": {"compaction_immune": True},
        },
    ]

    summarizable, immune = engine.partition_for_compaction(session_id, messages)

    # Standard conversational turns and untagged system are summarizable
    assert len(summarizable) == 3
    assert summarizable[0]["content"] == "You are a helpful coding assistant."
    assert summarizable[1]["content"] == "Please review this pull request."
    assert summarizable[2]["content"] == "Here is some general banter..."

    # Immune nodes are safely shielded
    assert len(immune) == 2
    assert immune[0]["metadata"]["skill_id"] == "code_review_sop"  # type: ignore[index]
    assert immune[1]["metadata"]["compaction_immune"] is True  # type: ignore[index]


def test_re_anchor_between_summary_and_tail_with_fingerprint() -> None:
    """Verifies deterministic post-compaction re-anchoring between summary and tail."""
    config = SkillImmunityConfig(
        anchor_position=ReAnchorAnchorPosition.BETWEEN_SUMMARY_AND_TAIL,
        deterministic_sorting=True,
    )
    engine = ActiveSkillImmunityEngine(config=config)
    session_id = "session_test_003"

    engine.register_skill(
        session_id,
        ActiveSkillSpec(
            skill_id="deploy_guard",
            name="Deploy Guard SOP",
            sop_rules=["Step 1: Run pre-flight checks", "Step 2: Require confirmation"],
            system_prompt_patch="Never execute destructive migrations without approval.",
        ),
    )

    # Simulated post-compaction message sequence
    compacted_messages: list[dict[str, object]] = [
        {"role": "system", "content": "Base system prompt."},
        {
            "role": "system",
            "content": "Summary of previous 40 turns: User refactored user auth.",
            "metadata": {"compaction_summary": True},
        },
        {"role": "user", "content": "Now execute deployment to staging."},
    ]

    result_msgs, outcome = engine.re_anchor_active_skills(session_id, compacted_messages)

    assert outcome.re_anchored is True
    assert outcome.skill_count == 1
    assert len(outcome.cache_fingerprint) == 64
    assert "<active_skills>" in outcome.re_anchored_xml
    assert 'skill id="deploy_guard"' in outcome.re_anchored_xml
    assert "<rule>Step 1: Run pre-flight checks</rule>" in outcome.re_anchored_xml

    # Check insertion position: between summary (index 1) and user prompt (now index 3)
    assert len(result_msgs) == 4
    assert result_msgs[0]["role"] == "system"
    assert result_msgs[1]["metadata"]["compaction_summary"] is True  # type: ignore[index]
    # Re-anchored node at index 2
    assert result_msgs[2]["role"] == "system"
    assert "[Active Skills Instruction Frame - Zero Compaction Decay]" in str(result_msgs[2]["content"])
    assert result_msgs[3]["content"] == "Now execute deployment to staging."


def test_re_anchor_after_system_and_prompt_tail_modes() -> None:
    """Verifies AFTER_SYSTEM and PROMPT_TAIL placement modes."""
    # 1. AFTER_SYSTEM
    engine_after = ActiveSkillImmunityEngine(
        config=SkillImmunityConfig(anchor_position=ReAnchorAnchorPosition.AFTER_SYSTEM)
    )
    session_id = "session_test_004"
    engine_after.register_skill(
        session_id,
        ActiveSkillSpec(skill_id="skill_x", name="Skill X", sop_rules=["Rule X"]),
    )

    raw_msgs: list[dict[str, object]] = [
        {"role": "system", "content": "Base prompt."},
        {"role": "user", "content": "Hello."},
    ]
    res_after, outcome_after = engine_after.re_anchor_active_skills(session_id, raw_msgs)
    assert outcome_after.re_anchored is True
    assert len(res_after) == 3
    assert res_after[0]["content"] == "Base prompt."
    assert "Active Skills" in str(res_after[1]["content"])
    assert res_after[2]["content"] == "Hello."

    # 2. PROMPT_TAIL
    engine_tail = ActiveSkillImmunityEngine(
        config=SkillImmunityConfig(anchor_position=ReAnchorAnchorPosition.PROMPT_TAIL)
    )
    engine_tail.register_skill(
        session_id,
        ActiveSkillSpec(skill_id="skill_y", name="Skill Y", sop_rules=["Rule Y"]),
    )
    res_tail, outcome_tail = engine_tail.re_anchor_active_skills(session_id, raw_msgs)
    assert outcome_tail.re_anchored is True
    assert len(res_tail) == 3
    assert res_tail[0]["content"] == "Base prompt."
    assert res_tail[1]["content"] == "Hello."
    assert "Active Skills" in str(res_tail[2]["content"])
