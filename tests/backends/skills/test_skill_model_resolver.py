"""Unit tests for Skill Specialized Model Resolver & Frontmatter parsing.

Tests cover:
- Parsing `specialized-model` / `specialized_model` and `model-tier` from SKILL.md Frontmatter.
- Accurate model resolution when specialized_model is explicitly present in available pool.
- Model tier fallback mapping when specialized_model is absent or invalid.
- Graceful degradation to agent default model when pool lacks specialized models.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter
from myrm_agent_harness.backends.skills.model_resolver import (
    DEFAULT_TIER_MAPPING,
    SkillModelResolutionSource,
    SkillModelResolver,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata


def test_frontmatter_specialized_model_parsing() -> None:
    content = """---
name: ast-optimizer
description: Specialized AST refactoring and code simplification engine
specialized-model: qwen-2.5-coder-1.5b
model-tier: fast
---
# Instructions
Transform Python code cleanly.
"""
    meta = parse_skill_frontmatter(content, "ast-optimizer")
    assert meta.specialized_model == "qwen-2.5-coder-1.5b"
    assert meta.model_tier == "fast"


def test_frontmatter_snake_case_specialized_model_parsing() -> None:
    content = """---
name: sql-generator
description: High-performance SQL queries generator
specialized_model: deepseek-coder-6.7b
model_tier: reasoning
---
# Instructions
Generate optimized Postgres queries.
"""
    meta = parse_skill_frontmatter(content, "sql-generator")
    assert meta.specialized_model == "deepseek-coder-6.7b"
    assert meta.model_tier == "reasoning"


def test_skill_model_resolver_explicit_match() -> None:
    skill = SkillMetadata(
        name="code-refactor",
        description="Refactor code",
        specialized_model="qwen-2.5-coder-1.5b",
        model_tier="fast",
    )
    available_models = ["claude-3-5-sonnet", "qwen-2.5-coder-1.5b", "deepseek-v3"]
    result = SkillModelResolver.resolve_model_for_skill(
        skill=skill,
        default_model="claude-3-5-sonnet",
        available_models=available_models,
    )
    assert result.selected_model == "qwen-2.5-coder-1.5b"
    assert result.resolution_source == SkillModelResolutionSource.EXPLICIT_SKILL_MODEL
    assert not result.is_fallback
    assert result.declared_model == "qwen-2.5-coder-1.5b"


def test_skill_model_resolver_tier_mapping_fallback() -> None:
    skill = SkillMetadata(
        name="deep-math-solver",
        description="Solve complex mathematical proofs",
        specialized_model="specialized-math-70b-unavailable",
        model_tier="reasoning",
    )
    available_models = ["claude-3-5-sonnet", "deepseek-reasoner"]
    result = SkillModelResolver.resolve_model_for_skill(
        skill=skill,
        default_model="claude-3-5-sonnet",
        available_models=available_models,
    )
    # The explicit model was not available, but the tier 'reasoning' mapped to 'deepseek-reasoner' which IS available
    assert result.selected_model == "deepseek-reasoner"
    assert result.resolution_source == SkillModelResolutionSource.TIER_MAPPING
    assert result.is_fallback is True
    assert result.declared_tier == "reasoning"


def test_skill_model_resolver_agent_default_fallback() -> None:
    skill = SkillMetadata(
        name="custom-worker",
        description="General worker",
        specialized_model="unavailable-model-slug",
        model_tier="unknown-tier",
    )
    available_models = ["claude-3-5-sonnet"]
    result = SkillModelResolver.resolve_model_for_skill(
        skill=skill,
        default_model="claude-3-5-sonnet",
        available_models=available_models,
    )
    assert result.selected_model == "claude-3-5-sonnet"
    assert result.resolution_source == SkillModelResolutionSource.FALLBACK
    assert result.is_fallback is True


def test_skill_model_resolver_no_overrides_declared() -> None:
    skill = SkillMetadata(
        name="plain-skill",
        description="Standard plain skill without model hints",
    )
    result = SkillModelResolver.resolve_model_for_skill(
        skill=skill,
        default_model="gpt-4o",
        available_models=["gpt-4o", "claude-3-5-sonnet"],
    )
    assert result.selected_model == "gpt-4o"
    assert result.resolution_source == SkillModelResolutionSource.AGENT_DEFAULT
    assert result.is_fallback is False
