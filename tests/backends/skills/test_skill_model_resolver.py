"""Unit tests for Skill Specialized Model Resolver and Model-As-A-Skill Hybrid Engine."""

from __future__ import annotations

from myrm_agent_harness.backends.skills._utils import parse_skill_metadata
from myrm_agent_harness.backends.skills.model_resolver import (
    DEFAULT_TIER_MODELS,
    SkillModelResolutionSource,
    SkillModelResolver,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata


def test_frontmatter_specialized_model_parsing() -> None:
    """Verify parsing of specialized-model and model-tier from SKILL.md frontmatter."""
    content = """---
name: code-ast-refactor
description: High-precision code AST refactoring tool
specialized-model: qwen-2.5-coder-1.5b
model-tier: simple
---
# Instructions
Transform Python code AST.
"""
    meta = parse_skill_metadata(content, "code-ast-refactor")
    assert meta.name == "code-ast-refactor"
    assert meta.specialized_model == "qwen-2.5-coder-1.5b"
    assert meta.model_tier == "simple"


def test_resolve_explicit_specialized_model() -> None:
    """Verify explicit model resolution when model is available."""
    meta = SkillMetadata(
        name="code-refactor",
        description="test",
        specialized_model="qwen-2.5-coder-1.5b",
        model_tier="simple",
    )
    res = SkillModelResolver.resolve(
        skill_metadata=meta,
        default_model="claude-3-5-sonnet",
        available_models={"qwen-2.5-coder-1.5b", "claude-3-5-sonnet"},
    )
    assert res.selected_model == "qwen-2.5-coder-1.5b"
    assert res.source == SkillModelResolutionSource.EXPLICIT_MODEL
    assert res.is_fallback is False


def test_resolve_tier_mapping_fallback_when_explicit_unavailable() -> None:
    """Verify fallback to tier mapping when explicit model is missing from available models."""
    meta = SkillMetadata(
        name="math-solver",
        description="test",
        specialized_model="unsupported-math-model-1b",
        model_tier="reasoning",
    )
    res = SkillModelResolver.resolve(
        skill_metadata=meta,
        default_model="claude-3-5-sonnet",
        available_models={"deepseek-reasoner", "claude-3-5-sonnet"},
    )
    assert res.selected_model == "deepseek-reasoner"
    assert res.source == SkillModelResolutionSource.FALLBACK
    assert res.is_fallback is True
    assert "fallback from unavailable" in res.reason


def test_resolve_tier_mapping_direct() -> None:
    """Verify resolution directly from declared tier when no explicit model is set."""
    meta = SkillMetadata(
        name="fast-classifier",
        description="test",
        model_tier="simple",
    )
    res = SkillModelResolver.resolve(
        skill_metadata=meta,
        default_model="claude-3-5-sonnet",
        available_models={"qwen-2.5-coder-1.5b", "claude-3-5-sonnet"},
    )
    assert res.selected_model == DEFAULT_TIER_MODELS["simple"]
    assert res.source == SkillModelResolutionSource.TIER_MAPPING
    assert res.is_fallback is False


def test_resolve_agent_default_fallback() -> None:
    """Verify fallback to agent default model when no model or tier is specified."""
    meta = SkillMetadata(
        name="general-helper",
        description="test",
    )
    res = SkillModelResolver.resolve(
        skill_metadata=meta,
        default_model="claude-3-7-sonnet",
    )
    assert res.selected_model == "claude-3-7-sonnet"
    assert res.source == SkillModelResolutionSource.AGENT_DEFAULT
    assert res.is_fallback is False
    assert res.to_dict()["selected_model"] == "claude-3-7-sonnet"
