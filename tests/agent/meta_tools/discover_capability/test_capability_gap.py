"""Tests for capability gap detection."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.discover_capability.capability_gap import (
    detect_capability_gap,
    detect_skill_gap,
)


def test_detect_capability_gap_browser_when_disabled() -> None:
    hit = detect_capability_gap("please browse this website", frozenset({"web", "memory", "file_ops", "shell"}))
    assert hit is not None
    assert hit.tool_id == "browser"


def test_detect_capability_gap_none_when_enabled() -> None:
    groups = frozenset({"web", "memory", "file_ops", "shell", "browser"})
    assert detect_capability_gap("open the website", groups) is None


def test_detect_skill_gap_unbound_skill() -> None:
    hit = detect_skill_gap(
        "use github_pr_skill to review",
        bound_skill_names=frozenset({"other_skill"}),
        library_skill_names=frozenset({"github_pr_skill", "other_skill"}),
    )
    assert hit is not None
    assert hit.skill_id == "github_pr_skill"


def test_detect_skill_gap_ignores_bound_skill() -> None:
    hit = detect_skill_gap(
        "use github_pr_skill",
        bound_skill_names=frozenset({"github_pr_skill"}),
        library_skill_names=frozenset({"github_pr_skill"}),
    )
    assert hit is None


def test_detect_capability_gap_empty_query() -> None:
    assert detect_capability_gap("   ", frozenset()) is None


def test_detect_skill_gap_ignores_unknown_library_skill() -> None:
    hit = detect_skill_gap(
        "use ghost_skill",
        bound_skill_names=frozenset(),
        library_skill_names=frozenset({"github_pr_skill"}),
    )
    assert hit is None


def test_format_capability_gap_block() -> None:
    from myrm_agent_harness.agent.meta_tools.discover_capability.capability_gap import (
        CapabilityGapHit,
        format_capability_gap_block,
    )

    block = format_capability_gap_block(CapabilityGapHit(tool_id="browser", tool_group="browser"))
    assert "<CapabilityGap>" in block
    assert '"tool_id": "browser"' in block


def test_format_skill_gap_block() -> None:
    from myrm_agent_harness.agent.meta_tools.discover_capability.capability_gap import (
        SkillGapHit,
        format_skill_gap_block,
    )

    block = format_skill_gap_block(SkillGapHit(skill_id="github_pr_skill"))
    assert "<SkillGap>" in block
    assert '"skill_id": "github_pr_skill"' in block
