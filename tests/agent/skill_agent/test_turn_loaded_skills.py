"""Turn loaded skills receipt payload for message_end metadata."""

from __future__ import annotations

from myrm_agent_harness.agent.skill_agent.context import (
    add_loaded_skill,
    reset_bound_skills_receipt,
    reset_loaded_skills,
    set_bound_skills_receipt,
)
from myrm_agent_harness.agent.skill_agent.turn_loaded_skills import build_turn_loaded_skills_payload
from myrm_agent_harness.backends.skills.types import SkillMetadata


def test_build_turn_loaded_skills_payload() -> None:
    reset_loaded_skills()
    add_loaded_skill(
        SkillMetadata(
            name="weekly-report",
            description="d",
            version="1.2.0",
            storage_skill_id="skill-abc",
            content_hash="sha256-deadbeef",
        )
    )
    payload = build_turn_loaded_skills_payload()
    assert len(payload) == 1
    row = payload[0]
    assert row["name"] == "weekly-report"
    assert row["id"] == "skill-abc"
    assert row["content_hash"] == "sha256-deadbeef"
    assert row["version"] == "1.2.0"
    assert row["partial"] is False
    reset_loaded_skills()
    reset_bound_skills_receipt()


def test_build_turn_loaded_skills_includes_bound_only() -> None:
    reset_loaded_skills()
    reset_bound_skills_receipt()
    set_bound_skills_receipt(
        [
            SkillMetadata(name="bound-only", description="d", storage_skill_id="b-1"),
            SkillMetadata(name="also-loaded", description="d", storage_skill_id="b-2"),
        ]
    )
    add_loaded_skill(
        SkillMetadata(name="also-loaded", description="d", storage_skill_id="b-2", content_hash="h")
    )
    payload = build_turn_loaded_skills_payload()
    assert len(payload) == 2
    by_name = {str(row["name"]): row for row in payload}
    assert by_name["also-loaded"]["partial"] is False
    assert by_name["bound-only"]["partial"] is True
    reset_loaded_skills()
    reset_bound_skills_receipt()
