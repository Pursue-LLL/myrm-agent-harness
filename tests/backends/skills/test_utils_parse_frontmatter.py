"""Tests for parse_skill_frontmatter and primary_env propagation."""

import pytest

from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
from myrm_agent_harness.backends.skills._utils import (
    SkillMetadataError,
    parse_skill_frontmatter,
)
from myrm_agent_harness.backends.skills.types import SkillTrust


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
    assert (
        fm.allowed_tools
        == "browser_navigate browser_inspect browser_snapshot browser_interact browser_extract browser_manage"
    )


def test_parse_skill_frontmatter_missing_required():
    content = """---
name: Missing description
---
pass"""
    with pytest.raises(SkillMetadataError, match="Required field 'description' missing"):
        parse_skill_frontmatter(content, "test_3")


# ── primary_env field parsing ────────────────────────────────────────────


def test_parse_skill_frontmatter_primary_env_camel_case():
    content = "---\ndescription: test\nprimaryEnv: BRAVE_API_KEY\n---\n# Skill\n"
    fm = parse_skill_frontmatter(content, "test")
    assert fm.primary_env == "BRAVE_API_KEY"


def test_parse_skill_frontmatter_primary_env_snake_case():
    content = "---\ndescription: test\nprimary_env: OPENAI_API_KEY\n---\n# Skill\n"
    fm = parse_skill_frontmatter(content, "test")
    assert fm.primary_env == "OPENAI_API_KEY"


def test_parse_skill_frontmatter_primary_env_defaults_none():
    content = "---\ndescription: test\n---\n# Skill\n"
    fm = parse_skill_frontmatter(content, "test")
    assert fm.primary_env is None


def test_parse_skill_frontmatter_primary_env_empty_string_treated_as_none():
    content = '---\ndescription: test\nprimaryEnv: ""\n---\n# Skill\n'
    fm = parse_skill_frontmatter(content, "test")
    assert fm.primary_env is None


def test_parse_skill_frontmatter_primary_env_whitespace_treated_as_none():
    content = "---\ndescription: test\nprimaryEnv: '   '\n---\n# Skill\n"
    fm = parse_skill_frontmatter(content, "test")
    assert fm.primary_env is None


# ── build_skill_metadata() primary_env propagation ───────────────────────


def test_build_skill_metadata_primary_env_propagated():
    content = "---\ndescription: test\nprimaryEnv: SOME_KEY\n---\n# Skill\n"
    fm = parse_skill_frontmatter(content, "my-skill")
    meta = build_skill_metadata(
        skill_name="my-skill",
        frontmatter=fm,
        storage_path="/tmp/skills/my-skill",
        content=content,
        trust=SkillTrust.INSTALLED,
    )
    assert meta.primary_env == "SOME_KEY"


def test_build_skill_metadata_primary_env_none():
    content = "---\ndescription: test\n---\n# Skill\n"
    fm = parse_skill_frontmatter(content, "my-skill")
    meta = build_skill_metadata(
        skill_name="my-skill",
        frontmatter=fm,
        storage_path="/tmp/skills/my-skill",
        content=content,
        trust=SkillTrust.INSTALLED,
    )
    assert meta.primary_env is None


# ── required_permissions parsing ─────────────────────────────────────────


def test_parse_skill_frontmatter_required_permissions():
    content = """---
description: test
required_permissions:
  - file_read
  - shell_exec
  - network_access
---
# Skill
"""
    fm = parse_skill_frontmatter(content, "my-skill")
    assert [p.value for p in fm.required_permissions] == [
        "file_read",
        "shell_exec",
        "network_access",
    ]


def test_parse_skill_frontmatter_required_permissions_empty_when_absent():
    content = "---\ndescription: test\n---\n# Skill\n"
    fm = parse_skill_frontmatter(content, "my-skill")
    assert fm.required_permissions == []


def test_parse_skill_frontmatter_required_permissions_skips_unknown():
    """Unknown permission names are skipped with a warning, not fatal."""
    content = """---
description: test
required_permissions:
  - file_write
  - not_a_real_permission
  - shell_exec
---
# Skill
"""
    fm = parse_skill_frontmatter(content, "my-skill")
    assert [p.value for p in fm.required_permissions] == ["file_write", "shell_exec"]


def test_build_skill_metadata_required_permissions_propagated():
    content = """---
description: test
required_permissions:
  - file_write
  - code_interpreter
---
# Skill
"""
    fm = parse_skill_frontmatter(content, "my-skill")
    meta = build_skill_metadata(
        skill_name="my-skill",
        frontmatter=fm,
        storage_path="/tmp/skills/my-skill",
        content=content,
        trust=SkillTrust.INSTALLED,
    )
    assert [p.value for p in meta.required_permissions] == [
        "file_write",
        "code_interpreter",
    ]
