"""Tests for parse_skill_frontmatter."""

import pytest

from myrm_agent_harness.backends.skills._utils import SkillMetadataError, parse_skill_frontmatter


def test_parse_skill_frontmatter_full():
    content = """---
name: Full Skill
description: A very full skill
version: 1.0.0
category: utility
model-invocable: true
user-invocable: true
primary_env: OPENAI_API_KEY
required_credential_files:
  - test.json
credential_env_mapping:
  OPENAI_API_KEY: test.json
evolution-locked: true
---
def main(): pass"""
    fm = parse_skill_frontmatter(content, "test_1")
    assert fm.name == "Full Skill"
    assert fm.description == "A very full skill"
    assert fm.version == "1.0.0"
    assert fm.category == "utility"
    assert fm.model_invocable is True
    assert fm.user_invocable is True
    assert fm.primary_env == "OPENAI_API_KEY"
    assert fm.required_credential_files == ["test.json"]
    assert fm.credential_env_mapping == {"OPENAI_API_KEY": "test.json"}
    assert fm.evolution_locked is True


def test_parse_skill_frontmatter_aliases():
    content = """---
name: Full Skill 2
description: A very full skill
disable-model-invocation: true
evolution_locked: false
---
def main(): pass"""
    fm = parse_skill_frontmatter(content, "test_2")
    assert fm.model_invocable is False
    assert fm.evolution_locked is False


def test_parse_skill_frontmatter_allowed_tools():
    content = """---
name: browser-skill
description: A skill with allowed tools
allowed-tools: browser_navigate browser_inspect browser_snapshot
---
Use browser tools."""
    fm = parse_skill_frontmatter(content, "browser-skill")
    assert fm.allowed_tools == "browser_navigate browser_inspect browser_snapshot"


def test_parse_skill_frontmatter_category_and_tags():
    """Verify category is parsed; tags are passed through YAML but not a SkillFrontmatter attr."""
    content = """---
name: tagged-skill
description: A skill with category
category: development
tags:
  - qa
  - testing
---
Body text."""
    fm = parse_skill_frontmatter(content, "tagged-skill")
    assert fm.category == "development"


def test_parse_skill_frontmatter_self_qa_format():
    """Integration test: parse the exact frontmatter format used by self-qa SKILL.md."""
    content = """---
description: >-
  Automated QA testing for web applications. Systematically discovers all interactive
  elements, tests each one, audits accessibility via ARIA tree, detects visual
  regressions, and generates a structured QA report.
name: self-qa
tags:
  - qa
  - testing
  - browser
category: development
allowed-tools: browser_navigate browser_inspect browser_snapshot browser_interact browser_extract browser_manage
---

# Self QA
You are a QA engineer."""
    fm = parse_skill_frontmatter(content, "self-qa")
    assert fm.name == "self-qa"
    assert "Automated QA testing" in fm.description
    assert fm.category == "development"
    assert fm.allowed_tools == "browser_navigate browser_inspect browser_snapshot browser_interact browser_extract browser_manage"


def test_parse_skill_frontmatter_missing_required():
    content = """---
name: Missing description
---
pass"""
    with pytest.raises(SkillMetadataError, match="Required field 'description' missing"):
        parse_skill_frontmatter(content, "test_3")
