"""Tests for the skill content security validator."""

import pytest

from myrm_agent_harness.agent.skills.optimization import SecurityConfig, SkillSecurityValidator

_VALID_SKILL = """---
name: test-skill
description: A harmless skill
---

# Harmless

Summarise the document."""


@pytest.fixture
def validator() -> SkillSecurityValidator:
    return SkillSecurityValidator(SecurityConfig())


def test_valid_skill_passes(validator: SkillSecurityValidator) -> None:
    result = validator.validate_skill(_VALID_SKILL)

    assert result.passed
    assert result.is_safe
    assert result.issues == []


@pytest.mark.parametrize("payload", ["rm -rf /", "eval(user_input)", "DROP TABLE users", "os.system('id')"])
def test_dangerous_pattern_is_rejected(validator: SkillSecurityValidator, payload: str) -> None:
    result = validator.validate_skill(_VALID_SKILL + f"\n\n{payload}\n")

    assert not result.passed
    assert any("Dangerous pattern detected" in issue for issue in result.issues)


def test_missing_frontmatter_is_rejected(validator: SkillSecurityValidator) -> None:
    result = validator.validate_skill("# No frontmatter here")

    assert not result.passed
    assert any("frontmatter" in issue.lower() for issue in result.issues)


def test_enabled_sandbox_validation_fails_closed() -> None:
    validator = SkillSecurityValidator(SecurityConfig(enable_sandbox_validation=True))

    result = validator.validate_skill(_VALID_SKILL)

    assert not result.passed
    assert any("Sandbox validation" in issue for issue in result.issues)
