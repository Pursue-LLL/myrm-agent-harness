"""Tests for Skill Optimizer"""

from unittest.mock import AsyncMock, Mock

import pytest

from myrm_agent_harness.agent.skills.optimization import (
    OptimizationConfig,
    SkillOptimizer,
    SkillQualityScore,
    SkillSecurityValidator,
    SkillType,
)


@pytest.fixture
def mock_llm():
    """Mock LLM"""
    llm = Mock()
    valid_skill_content = """---
name: test-skill
description: Optimized test skill
version: 2.0
---

# Optimized Skill

Improved implementation with better performance."""
    llm.ainvoke = AsyncMock(return_value=Mock(content=valid_skill_content))
    return llm


@pytest.fixture
def config():
    """Test config"""
    return OptimizationConfig.development()


@pytest.fixture
def security_validator(config):
    """Security validator"""
    return SkillSecurityValidator(config.security)


@pytest.fixture
def optimizer(mock_llm, config, security_validator):
    """Skill optimizer"""
    return SkillOptimizer(mock_llm, config, security_validator)


@pytest.fixture
def mock_skill():
    """Mock skill metadata"""
    skill = Mock()
    skill.name = "test-skill"
    skill.description = "Test skill"
    skill.storage_path = "users/test-user/skills/test-skill"
    return skill


@pytest.fixture
def quality_score():
    """Quality score"""
    return SkillQualityScore(
        success_rate=0.5, token_efficiency=0.6, execution_time=0.7, user_satisfaction=0.4, call_frequency=0.3
    )


@pytest.mark.asyncio
async def test_detect_skill_type_user(optimizer, mock_skill):
    """Test USER skill type detection"""
    skill_type = optimizer._detect_skill_type(mock_skill)
    assert skill_type == SkillType.USER


@pytest.mark.asyncio
async def test_detect_skill_type_prebuilt(optimizer):
    """Test PREBUILT skill type detection"""
    skill = Mock()
    skill.name = "prebuilt-skill"
    skill.storage_path = "skills/prebuilt/test"

    skill_type = optimizer._detect_skill_type(skill)
    assert skill_type == SkillType.PREBUILT


@pytest.mark.asyncio
async def test_optimize_user_skill_no_lock(optimizer, mock_skill, quality_score):
    """Test USER skill optimization (no lock needed)"""
    result = await optimizer.optimize_skill(mock_skill, quality_score)

    assert result.skill_id == "test-skill"
    assert result.skill_type == SkillType.USER
    assert result.security_validation.passed


@pytest.mark.asyncio
async def test_overall_score_calculation(quality_score):
    """Test overall score calculation"""
    score = quality_score.overall_score

    assert 0 <= score <= 1
    assert isinstance(score, float)
