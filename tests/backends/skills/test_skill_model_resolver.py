"""Unit tests for Skill Frontmatter parsing of the specialized model and model tier.

Tests cover:
- Parsing `specialized-model` / `specialized_model` and `model-tier` / `model_tier` from SKILL.md Frontmatter.
"""

from __future__ import annotations

from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter


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
