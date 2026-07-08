"""Tests for capability gap detection."""

from __future__ import annotations

import pytest

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


def test_detect_capability_gap_render_ui_when_disabled() -> None:
    hit = detect_capability_gap(
        "please render ui form",
        frozenset({"web", "memory", "file_ops", "shell"}),
    )
    assert hit is not None
    assert hit.tool_id == "render_ui"


def test_detect_capability_gap_render_ui_zh_form_triggers() -> None:
    hit = detect_capability_gap(
        "帮我填表准备 staging 部署配置",
        frozenset({"web", "memory", "file_ops", "shell"}),
    )
    assert hit is not None
    assert hit.tool_id == "render_ui"


def test_detect_capability_gap_none_when_render_ui_enabled() -> None:
    groups = frozenset({"web", "memory", "file_ops", "shell", "render_ui"})
    assert detect_capability_gap("please render ui form", groups) is None


def test_detect_capability_gap_none_when_image_generation_enabled() -> None:
    groups = frozenset({"web", "memory", "file_ops", "shell", "image_generation"})
    assert detect_capability_gap("generate image of a cat", groups) is None


def test_detect_capability_gap_image_when_disabled() -> None:
    hit = detect_capability_gap(
        "generate image of a cat",
        frozenset({"web", "memory", "file_ops", "shell"}),
    )
    assert hit is not None
    assert hit.tool_id == "image_generation"


def test_detect_capability_gap_computer_use_when_disabled() -> None:
    hit = detect_capability_gap(
        "take a desktop screenshot",
        frozenset({"web", "memory", "file_ops", "shell"}),
    )
    assert hit is not None
    assert hit.tool_id == "computer_use"


def test_detect_capability_gap_none_when_computer_use_enabled() -> None:
    groups = frozenset({"web", "memory", "file_ops", "shell", "computer_use"})
    assert detect_capability_gap("take a desktop screenshot", groups) is None


@pytest.mark.parametrize(
    ("tool_id", "query", "group"),
    [
        ("wiki", "search my personal wiki", "wiki"),
        ("kanban", "move card on kanban board", "kanban"),
        ("cron", "create a cron job every day", "cron"),
        ("planning", "create multi-step plan for launch", "planning"),
        ("video_generation", "generate video from text prompt", "video_generation"),
        ("tts", "text to speech for this paragraph", "tts"),
    ],
)
def test_detect_capability_gap_all_triggers_when_group_disabled(
    tool_id: str,
    query: str,
    group: str,
) -> None:
    active = frozenset({"web", "memory"})
    hit = detect_capability_gap(query, active)
    assert hit is not None
    assert hit.tool_id == tool_id
    assert hit.tool_group == group


@pytest.mark.parametrize(
    ("group", "query"),
    [
        ("wiki", "search my personal wiki"),
        ("kanban", "move card on kanban board"),
        ("cron", "create a cron job every day"),
        ("planning", "create multi-step plan for launch"),
        ("video_generation", "generate video from text prompt"),
        ("tts", "text to speech for this paragraph"),
    ],
)
def test_detect_capability_gap_none_when_group_enabled(group: str, query: str) -> None:
    active = frozenset({"web", "memory", group})
    assert detect_capability_gap(query, active) is None


def test_detect_capability_gap_web_search_when_disabled() -> None:
    hit = detect_capability_gap(
        "search the web for apple news",
        frozenset({"memory", "file_ops", "shell"}),
    )
    assert hit is not None
    assert hit.tool_id == "web_search"
    assert hit.tool_group == "web"


def test_detect_capability_gap_memory_when_disabled() -> None:
    hit = detect_capability_gap(
        "remember this for next time",
        frozenset({"web", "file_ops", "shell"}),
    )
    assert hit is not None
    assert hit.tool_id == "memory"
    assert hit.tool_group == "memory"


def test_detect_capability_gap_answer_tool_when_disabled() -> None:
    hit = detect_capability_gap(
        "confirm with user before proceeding",
        frozenset({"web", "memory", "file_ops", "shell"}),
    )
    assert hit is not None
    assert hit.tool_id == "answer_tool"
    assert hit.tool_group == "answer_tool"


def test_detect_capability_gap_none_when_web_search_enabled() -> None:
    groups = frozenset({"web", "memory", "file_ops", "shell"})
    assert detect_capability_gap("search the web for news", groups) is None


def test_detect_capability_gap_web_search_zh_query() -> None:
    hit = detect_capability_gap(
        "网上搜一下苹果发布会",
        frozenset({"memory", "file_ops", "shell"}),
    )
    assert hit is not None
    assert hit.tool_id == "web_search"


def test_detect_capability_gap_no_false_positive_for_local_file_query() -> None:
    """Generic local queries without web-specific terms must not suggest web_search."""
    active = frozenset({"memory", "file_ops", "shell"})
    assert detect_capability_gap("list local documents", active) is None
    assert detect_capability_gap("summarize project readme", active) is None


def test_detect_capability_gap_baseline_file_ops_never_suggested() -> None:
    """file_ops/code_execute are runtime baseline — no GUI toggle, no gap hint."""
    active = frozenset({"web", "memory"})
    assert detect_capability_gap("grep pattern in repo files", active) is None
    assert detect_capability_gap("run shell bash terminal script", active) is None


def test_capability_gap_registry_covers_all_togglable_builtin_tool_ids() -> None:
    from myrm_agent_harness.agent.meta_tools.discover_capability.capability_gap import (
        BUILTIN_TOOL_ID_TO_GROUP,
        CAPABILITY_GAP_REGISTRY,
    )

    registry_ids = [entry.tool_id for entry in CAPABILITY_GAP_REGISTRY]
    assert len(registry_ids) == len(set(registry_ids))
    assert set(registry_ids) == set(BUILTIN_TOOL_ID_TO_GROUP)
    for entry in CAPABILITY_GAP_REGISTRY:
        assert BUILTIN_TOOL_ID_TO_GROUP[entry.tool_id] == entry.tool_group
        assert entry.triggers


def test_detect_capability_gap_first_match_wins() -> None:
    """Earlier CAPABILITY_GAP_REGISTRY entry wins when multiple could match."""
    active = frozenset({"web", "memory"})
    hit = detect_capability_gap("browse website and generate image", active)
    assert hit is not None
    assert hit.tool_id == "browser"


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
