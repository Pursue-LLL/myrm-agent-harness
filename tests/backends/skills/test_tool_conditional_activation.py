"""Tests for tool-based conditional skill activation.

Covers:
- skill_visible_for_tools() pure filter — all 4 field combinations
- Edge cases: empty lists (default), mixed conditions, all conditions
- TOOL_GROUP_MAP / TOOL_TO_GROUP / TOOL_GROUP_NAMES consistency
- _runtime.py group name validation warning
"""

from __future__ import annotations

import logging

from myrm_agent_harness.backends.skills.types import (
    SkillMetadata,
    SkillTrust,
    skill_visible_for_tools,
)
from myrm_agent_harness.core.security.tool_registry import (
    TOOL_GROUP_MAP,
    TOOL_GROUP_NAMES,
    TOOL_TO_GROUP,
)


def _make_skill(
    name: str = "test_skill",
    requires_tools: list[str] | None = None,
    fallback_for_tools: list[str] | None = None,
    requires_tool_groups: list[str] | None = None,
    fallback_for_tool_groups: list[str] | None = None,
) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description="test",
        trust=SkillTrust.INSTALLED,
        requires_tools=requires_tools or [],
        fallback_for_tools=fallback_for_tools or [],
        requires_tool_groups=requires_tool_groups or [],
        fallback_for_tool_groups=fallback_for_tool_groups or [],
    )


# ---------------------------------------------------------------------------
# TOOL_GROUP_MAP consistency checks
# ---------------------------------------------------------------------------

class TestToolGroupMapConsistency:
    def test_tool_to_group_covers_all_tools(self):
        all_tools = set()
        for tools in TOOL_GROUP_MAP.values():
            all_tools.update(tools)
        assert set(TOOL_TO_GROUP.keys()) == all_tools

    def test_tool_group_names_matches_keys(self):
        assert frozenset(TOOL_GROUP_MAP.keys()) == TOOL_GROUP_NAMES

    def test_no_tool_in_multiple_groups(self):
        seen: dict[str, str] = {}
        for group, tools in TOOL_GROUP_MAP.items():
            for tool in tools:
                assert tool not in seen, (
                    f"Tool '{tool}' in both '{seen[tool]}' and '{group}'"
                )
                seen[tool] = group

    def test_group_names_are_lowercase_identifiers(self):
        for name in TOOL_GROUP_NAMES:
            assert name == name.lower(), f"Group name '{name}' not lowercase"
            assert name.isidentifier() or "_" in name, (
                f"Group name '{name}' not a valid identifier"
            )


# ---------------------------------------------------------------------------
# skill_visible_for_tools — requires_tools
# ---------------------------------------------------------------------------

class TestRequiresTools:
    def test_empty_requires_always_visible(self):
        skill = _make_skill()
        assert skill_visible_for_tools(skill, frozenset(), frozenset()) is True

    def test_requires_present_visible(self):
        skill = _make_skill(requires_tools=["bash_code_execute_tool"])
        assert skill_visible_for_tools(
            skill, frozenset({"bash_code_execute_tool", "file_read_tool"}), frozenset()
        ) is True

    def test_requires_absent_hidden(self):
        skill = _make_skill(requires_tools=["bash_code_execute_tool"])
        assert skill_visible_for_tools(
            skill, frozenset({"file_read_tool"}), frozenset()
        ) is False

    def test_requires_multiple_all_present(self):
        skill = _make_skill(requires_tools=["bash_code_execute_tool", "file_read_tool"])
        assert skill_visible_for_tools(
            skill, frozenset({"bash_code_execute_tool", "file_read_tool", "web_search_tool"}), frozenset()
        ) is True

    def test_requires_multiple_one_missing(self):
        skill = _make_skill(requires_tools=["bash_code_execute_tool", "file_read_tool"])
        assert skill_visible_for_tools(
            skill, frozenset({"bash_code_execute_tool"}), frozenset()
        ) is False


# ---------------------------------------------------------------------------
# skill_visible_for_tools — fallback_for_tools
# ---------------------------------------------------------------------------

class TestFallbackForTools:
    def test_empty_fallback_always_visible(self):
        skill = _make_skill()
        assert skill_visible_for_tools(skill, frozenset(), frozenset()) is True

    def test_fallback_tool_present_hidden(self):
        skill = _make_skill(fallback_for_tools=["bash_code_execute_tool"])
        assert skill_visible_for_tools(
            skill, frozenset({"bash_code_execute_tool"}), frozenset()
        ) is False

    def test_fallback_tool_absent_visible(self):
        skill = _make_skill(fallback_for_tools=["bash_code_execute_tool"])
        assert skill_visible_for_tools(
            skill, frozenset({"web_search_tool"}), frozenset()
        ) is True

    def test_fallback_multiple_any_present_hidden(self):
        """ANY semantics: hidden when any one fallback tool is present."""
        skill = _make_skill(fallback_for_tools=["bash_code_execute_tool", "file_read_tool"])
        assert skill_visible_for_tools(
            skill, frozenset({"file_read_tool"}), frozenset()
        ) is False

    def test_fallback_multiple_none_present_visible(self):
        skill = _make_skill(fallback_for_tools=["bash_code_execute_tool", "file_read_tool"])
        assert skill_visible_for_tools(
            skill, frozenset({"web_search_tool"}), frozenset()
        ) is True


# ---------------------------------------------------------------------------
# skill_visible_for_tools — requires_tool_groups
# ---------------------------------------------------------------------------

class TestRequiresToolGroups:
    def test_requires_group_present_visible(self):
        skill = _make_skill(requires_tool_groups=["shell"])
        assert skill_visible_for_tools(
            skill, frozenset(), frozenset({"shell", "web"})
        ) is True

    def test_requires_group_absent_hidden(self):
        skill = _make_skill(requires_tool_groups=["shell"])
        assert skill_visible_for_tools(
            skill, frozenset(), frozenset({"web"})
        ) is False

    def test_requires_multiple_groups_all_present(self):
        skill = _make_skill(requires_tool_groups=["shell", "file_ops"])
        assert skill_visible_for_tools(
            skill, frozenset(), frozenset({"shell", "file_ops", "web"})
        ) is True

    def test_requires_multiple_groups_one_missing(self):
        skill = _make_skill(requires_tool_groups=["shell", "file_ops"])
        assert skill_visible_for_tools(
            skill, frozenset(), frozenset({"shell"})
        ) is False


# ---------------------------------------------------------------------------
# skill_visible_for_tools — fallback_for_tool_groups
# ---------------------------------------------------------------------------

class TestFallbackForToolGroups:
    def test_fallback_group_present_hidden(self):
        skill = _make_skill(fallback_for_tool_groups=["browser"])
        assert skill_visible_for_tools(
            skill, frozenset(), frozenset({"browser"})
        ) is False

    def test_fallback_group_absent_visible(self):
        skill = _make_skill(fallback_for_tool_groups=["browser"])
        assert skill_visible_for_tools(
            skill, frozenset(), frozenset({"shell"})
        ) is True

    def test_fallback_multiple_groups_any_present_hidden(self):
        """ANY semantics: hidden when any one fallback group is enabled."""
        skill = _make_skill(fallback_for_tool_groups=["browser", "shell"])
        assert skill_visible_for_tools(
            skill, frozenset(), frozenset({"shell"})
        ) is False

    def test_fallback_multiple_groups_none_present_visible(self):
        skill = _make_skill(fallback_for_tool_groups=["browser", "shell"])
        assert skill_visible_for_tools(
            skill, frozenset(), frozenset({"web", "memory"})
        ) is True


# ---------------------------------------------------------------------------
# Combined conditions
# ---------------------------------------------------------------------------

class TestCombinedConditions:
    def test_requires_tool_and_group_both_satisfied(self):
        skill = _make_skill(
            requires_tools=["bash_code_execute_tool"],
            requires_tool_groups=["shell"],
        )
        assert skill_visible_for_tools(
            skill, frozenset({"bash_code_execute_tool"}), frozenset({"shell"})
        ) is True

    def test_requires_tool_satisfied_group_not(self):
        skill = _make_skill(
            requires_tools=["bash_code_execute_tool"],
            requires_tool_groups=["browser"],
        )
        assert skill_visible_for_tools(
            skill, frozenset({"bash_code_execute_tool"}), frozenset({"shell"})
        ) is False

    def test_fallback_overrides_requires(self):
        """If requires is met but fallback is also triggered, skill is hidden."""
        skill = _make_skill(
            requires_tools=["web_search_tool"],
            fallback_for_tool_groups=["web"],
        )
        assert skill_visible_for_tools(
            skill, frozenset({"web_search_tool"}), frozenset({"web"})
        ) is False

    def test_all_conditions_satisfied(self):
        skill = _make_skill(
            requires_tools=["bash_code_execute_tool"],
            requires_tool_groups=["shell"],
            fallback_for_tools=["nonexistent_tool"],
            fallback_for_tool_groups=["nonexistent_group"],
        )
        assert skill_visible_for_tools(
            skill, frozenset({"bash_code_execute_tool"}), frozenset({"shell"})
        ) is True

    def test_dual_fallback_tool_and_group_tool_triggers(self):
        """Both fallback_for_tools and fallback_for_tool_groups set; tool triggers."""
        skill = _make_skill(
            fallback_for_tools=["bash_code_execute_tool"],
            fallback_for_tool_groups=["web"],
        )
        assert skill_visible_for_tools(
            skill, frozenset({"bash_code_execute_tool"}), frozenset({"memory"})
        ) is False

    def test_dual_fallback_tool_and_group_group_triggers(self):
        """Both fallback_for_tools and fallback_for_tool_groups set; group triggers."""
        skill = _make_skill(
            fallback_for_tools=["bash_code_execute_tool"],
            fallback_for_tool_groups=["web"],
        )
        assert skill_visible_for_tools(
            skill, frozenset({"file_read_tool"}), frozenset({"web"})
        ) is False

    def test_dual_fallback_neither_triggers_visible(self):
        """Both fallback_for_tools and fallback_for_tool_groups set; neither triggers."""
        skill = _make_skill(
            fallback_for_tools=["bash_code_execute_tool"],
            fallback_for_tool_groups=["web"],
        )
        assert skill_visible_for_tools(
            skill, frozenset({"file_read_tool"}), frozenset({"memory"})
        ) is True

    def test_requires_group_not_satisfied_fallback_tool_not_triggered(self):
        """requires_tool_groups fails, even if fallback_for_tools is not triggered."""
        skill = _make_skill(
            requires_tool_groups=["browser"],
            fallback_for_tools=["nonexistent"],
        )
        assert skill_visible_for_tools(
            skill, frozenset(), frozenset({"shell"})
        ) is False


# ---------------------------------------------------------------------------
# _runtime.py group name validation
# ---------------------------------------------------------------------------

class TestGroupNameValidation:
    def test_valid_group_names_no_warning(self, caplog):
        from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
        from myrm_agent_harness.backends.skills._utils import SkillFrontmatter

        fm = SkillFrontmatter(
            description="test",
            requires_tool_groups=["shell", "web"],
        )
        with caplog.at_level(logging.WARNING):
            build_skill_metadata(
                skill_name="valid_skill",
                frontmatter=fm,
                storage_path="test/valid_skill",
                content="# test\nsome content",
                trust=SkillTrust.INSTALLED,
            )
        assert "unknown groups" not in caplog.text

    def test_invalid_group_name_warns(self, caplog):
        from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
        from myrm_agent_harness.backends.skills._utils import SkillFrontmatter

        fm = SkillFrontmatter(
            description="test",
            requires_tool_groups=["shell", "totally_fake_group"],
        )
        with caplog.at_level(logging.WARNING):
            build_skill_metadata(
                skill_name="bad_skill",
                frontmatter=fm,
                storage_path="test/bad_skill",
                content="# test\nsome content",
                trust=SkillTrust.INSTALLED,
            )
        assert "unknown groups" in caplog.text
        assert "totally_fake_group" in caplog.text

    def test_invalid_fallback_group_name_warns(self, caplog):
        """Validate that fallback_for_tool_groups also triggers warning."""
        from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
        from myrm_agent_harness.backends.skills._utils import SkillFrontmatter

        fm = SkillFrontmatter(
            description="test",
            fallback_for_tool_groups=["bogus_group"],
        )
        with caplog.at_level(logging.WARNING):
            build_skill_metadata(
                skill_name="bad_fallback",
                frontmatter=fm,
                storage_path="test/bad_fallback",
                content="# test\nsome content",
                trust=SkillTrust.INSTALLED,
            )
        assert "unknown groups" in caplog.text
        assert "bogus_group" in caplog.text


# ---------------------------------------------------------------------------
# Frontmatter parsing of new fields
# ---------------------------------------------------------------------------

class TestFrontmatterParsing:
    def test_parse_requires_tools_kebab(self):
        from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter

        content = """---
description: test skill
requires-tools:
  - bash_code_execute_tool
  - file_read_tool
fallback-for-tool-groups:
  - browser
---
# Test
"""
        fm = parse_skill_frontmatter(content, skill_dir_name="test_skill")
        assert fm.requires_tools == ["bash_code_execute_tool", "file_read_tool"]
        assert fm.fallback_for_tool_groups == ["browser"]

    def test_parse_requires_tools_snake(self):
        from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter

        content = """---
description: test skill
requires_tool_groups:
  - shell
  - web
---
# Test
"""
        fm = parse_skill_frontmatter(content, skill_dir_name="test_skill")
        assert fm.requires_tool_groups == ["shell", "web"]

    def test_parse_empty_defaults(self):
        from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter

        content = """---
description: test skill
---
# Test
"""
        fm = parse_skill_frontmatter(content, skill_dir_name="test_skill")
        assert fm.requires_tools == []
        assert fm.fallback_for_tools == []
        assert fm.requires_tool_groups == []
        assert fm.fallback_for_tool_groups == []

    def test_parse_all_four_fields_simultaneously(self):
        from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter

        content = """---
description: full conditional skill
requires-tools:
  - bash_code_execute_tool
fallback-for-tools:
  - web_search_tool
requires-tool-groups:
  - shell
fallback-for-tool-groups:
  - browser
---
# Full
"""
        fm = parse_skill_frontmatter(content, skill_dir_name="full_skill")
        assert fm.requires_tools == ["bash_code_execute_tool"]
        assert fm.fallback_for_tools == ["web_search_tool"]
        assert fm.requires_tool_groups == ["shell"]
        assert fm.fallback_for_tool_groups == ["browser"]

    def test_parse_single_string_value_coerced_to_list(self):
        """_extract_str_list supports a bare string (not a list)."""
        from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter

        content = """---
description: single value skill
requires-tools: bash_code_execute_tool
---
# Test
"""
        fm = parse_skill_frontmatter(content, skill_dir_name="single_val")
        assert fm.requires_tools == ["bash_code_execute_tool"]


# ---------------------------------------------------------------------------
# build_skill_metadata end-to-end field propagation
# ---------------------------------------------------------------------------

class TestBuildSkillMetadataFieldPropagation:
    """Verify frontmatter conditional fields propagate to SkillMetadata."""

    def test_all_four_fields_reach_metadata(self):
        from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
        from myrm_agent_harness.backends.skills._utils import SkillFrontmatter

        fm = SkillFrontmatter(
            description="prop test",
            requires_tools=["bash_code_execute_tool"],
            fallback_for_tools=["web_search_tool"],
            requires_tool_groups=["shell"],
            fallback_for_tool_groups=["browser"],
        )
        meta = build_skill_metadata(
            skill_name="prop_skill",
            frontmatter=fm,
            storage_path="test/prop_skill",
            content="# test\nprop content",
            trust=SkillTrust.INSTALLED,
        )
        assert meta.requires_tools == ["bash_code_execute_tool"]
        assert meta.fallback_for_tools == ["web_search_tool"]
        assert meta.requires_tool_groups == ["shell"]
        assert meta.fallback_for_tool_groups == ["browser"]

    def test_empty_fields_default_in_metadata(self):
        from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
        from myrm_agent_harness.backends.skills._utils import SkillFrontmatter

        fm = SkillFrontmatter(description="no conditions")
        meta = build_skill_metadata(
            skill_name="empty_cond",
            frontmatter=fm,
            storage_path="test/empty_cond",
            content="# test\nempty",
            trust=SkillTrust.TRUSTED,
        )
        assert meta.requires_tools == []
        assert meta.fallback_for_tools == []
        assert meta.requires_tool_groups == []
        assert meta.fallback_for_tool_groups == []
