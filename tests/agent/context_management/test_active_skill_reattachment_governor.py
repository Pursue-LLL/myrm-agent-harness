"""Unit tests for ActiveSkillReattachmentGovernor."""

import pytest

from myrm_agent_harness.agent.context_management.skill_sentinel import (
    ActiveSkillReattachmentGovernor,
    SkillBudgetPolicy,
)


def test_fingerprint_anchoring_and_single_skill_5k_cap() -> None:
    """Verify skill fingerprint anchoring and strict 5,000 token single-skill cap."""
    governor = ActiveSkillReattachmentGovernor(
        policy=SkillBudgetPolicy(max_single_skill_tokens=5000, max_total_reattached_tokens=25000)
    )
    session_id = "sess-skill-001"

    # Register an oversized skill SOP (6,000 tokens = ~24,000 chars)
    oversized_body = "RULE: Strict compliance item.\n" * 800
    record = governor.register_skill_activation(
        session_id=session_id,
        turn_index=1,
        skill_name="compliance-checker",
        instruction_body=oversized_body,
    )

    assert record.skill_name == "compliance-checker"
    assert len(record.content_hash) == 16
    assert record.estimated_tokens > 5000

    messages = [
        {"role": "system", "content": "Base assistant instructions."},
        {"role": "user", "content": "Analyze regulatory filings."},
    ]

    reconstructed, result = governor.governed_post_compaction_reattach(
        session_id=session_id,
        turn_index=5,
        messages=messages,
    )

    assert len(result.reattached_skills) == 1
    reattached = result.reattached_skills[0]
    assert reattached.skill_name == "compliance-checker"
    assert reattached.truncated is True
    assert reattached.tokens_used == 5000
    assert "Truncated to 5,000 tokens" in reattached.rendered_content

    # Reconstructed message stream must contain the active skill SOP right after system message
    assert len(reconstructed) == 3
    assert reconstructed[0]["role"] == "system"
    assert "<active_skill_sop>" in reconstructed[1]["content"]
    assert reconstructed[2]["role"] == "user"


def test_cumulative_25k_budget_and_earliest_skill_drop_out() -> None:
    """Verify that earlier skills drop out when cumulative budget (25k) is exceeded."""
    governor = ActiveSkillReattachmentGovernor(
        policy=SkillBudgetPolicy(max_single_skill_tokens=5000, max_total_reattached_tokens=25000)
    )
    session_id = "sess-skill-002"

    # Register 6 distinct skills, each exactly 5,000 tokens (5,000 * 6 = 30,000 tokens)
    # Turn indices 10, 11, 12, 13, 14, 15
    for i in range(6):
        prefix = f"SOP for skill-{i}\n"
        body = prefix + ("x" * (20000 - len(prefix)))  # Exactly 20,000 chars = 5,000 tokens
        governor.register_skill_activation(
            session_id=session_id,
            turn_index=10 + i,
            skill_name=f"skill-{i}",
            instruction_body=body,
        )

    messages = [
        {"role": "system", "content": "Base system."},
        {"role": "user", "content": "Execute task."},
    ]

    _, result = governor.governed_post_compaction_reattach(
        session_id=session_id,
        turn_index=20,
        messages=messages,
    )

    # 5 skills fit in 25,000 tokens budget (5 * 5000 = 25000)
    assert len(result.reattached_skills) == 5
    assert result.total_reattached_tokens == 25000

    # Most recent first: skill-5, skill-4, skill-3, skill-2, skill-1 fit
    reattached_names = [s.skill_name for s in result.reattached_skills]
    assert reattached_names == ["skill-5", "skill-4", "skill-3", "skill-2", "skill-1"]

    # Earliest skill-0 dropped out entirely
    assert "skill-0" in result.dropped_skills


def test_atomic_replacement_of_old_sop_marker() -> None:
    """Verify that old active skill SOP markers are stripped and never duplicated."""
    governor = ActiveSkillReattachmentGovernor()
    session_id = "sess-skill-003"

    governor.register_skill_activation(
        session_id=session_id,
        turn_index=2,
        skill_name="git-workflow",
        instruction_body="Always verify branch before commit.",
    )

    # Messages already contain a stale active skill SOP
    messages = [
        {"role": "system", "content": "Base system."},
        {
            "role": "system",
            "content": "<active_skill_sop>\nOld stale skill content\n</active_skill_sop>",
        },
        {"role": "user", "content": "Commit changes."},
    ]

    reconstructed, _ = governor.governed_post_compaction_reattach(
        session_id=session_id,
        turn_index=3,
        messages=messages,
    )

    # Must only contain one <active_skill_sop> block
    sop_blocks = [
        m for m in reconstructed if "<active_skill_sop>" in m.get("content", "")
    ]
    assert len(sop_blocks) == 1
    assert "git-workflow" in sop_blocks[0]["content"]
    assert "Old stale skill content" not in sop_blocks[0]["content"]


def test_drift_detected_reinforcement_and_pinned_priority() -> None:
    """Verify drift detection triggers attention warnings and pinned skills take precedence."""
    governor = ActiveSkillReattachmentGovernor(
        policy=SkillBudgetPolicy(max_single_skill_tokens=5000, max_total_reattached_tokens=10000)
    )
    session_id = "sess-skill-004"

    # Register an older skill but PINNED (turn 1)
    governor.register_skill_activation(
        session_id=session_id,
        turn_index=1,
        skill_name="pinned-architecture-sop",
        instruction_body="Never use Any type; maintain <400 lines.",
        is_pinned=True,
    )

    # Register a newer skill (turn 5) with drift detected
    governor.register_skill_activation(
        session_id=session_id,
        turn_index=5,
        skill_name="frontend-styling",
        instruction_body="Use Tailwind utilities only.",
    )
    governor.mark_skill_drift_needed(session_id, "frontend-styling")

    messages = [
        {"role": "system", "content": "Base system."},
        {"role": "user", "content": "Develop UI component."},
    ]

    _, result = governor.governed_post_compaction_reattach(
        session_id=session_id,
        turn_index=6,
        messages=messages,
    )

    assert len(result.reattached_skills) == 2
    # Pinned skill must be prioritized first
    assert result.reattached_skills[0].skill_name == "pinned-architecture-sop"
    # Drifted skill must show attention banner
    drifted_block = result.reattached_skills[1]
    assert drifted_block.skill_name == "frontend-styling"
    assert "ATTENTION: Re-emphasized SOP due to detected rule drift" in drifted_block.rendered_content
