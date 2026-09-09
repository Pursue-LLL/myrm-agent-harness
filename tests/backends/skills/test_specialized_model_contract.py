"""Unit tests for Model-As-A-Skill Specialized Model & Complexity Tier Contract.

[INPUT]
- myrm_agent_harness.backends.skills._utils
- myrm_agent_harness.backends.skills._runtime

[OUTPUT]
- pytest suite verifying parsing and propagation of specialized_model and model_tier frontmatter attributes

[POS]
myrm-agent-harness/tests/backends/skills/test_specialized_model_contract.py
"""

import pytest

from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter
from myrm_agent_harness.backends.skills.types import SkillTrust


def test_specialized_model_frontmatter_parsing() -> None:
    content = """---
description: High-throughput code formatting and AST validation skill
specialized_model: qwen-2.5-coder-1.5b
model_tier: simple
---
# Python AST Formatter
Executes formatting without polluting main context.
"""
    frontmatter = parse_skill_frontmatter(content, "ast_formatter_skill")
    assert frontmatter.description == "High-throughput code formatting and AST validation skill"
    assert frontmatter.specialized_model == "qwen-2.5-coder-1.5b"
    assert frontmatter.model_tier == "simple"

    metadata = build_skill_metadata(
        skill_name="ast_formatter_skill",
        frontmatter=frontmatter,
        storage_path="/tmp/ast_formatter",
        content=content,
        trust=SkillTrust.TRUSTED,
    )
    assert metadata.specialized_model == "qwen-2.5-coder-1.5b"
    assert metadata.model_tier == "simple"


def test_kebab_case_and_camel_case_compatibility() -> None:
    content_kebab = """---
description: Fast markdown summarizing skill
specialized-model: gpt-4o-mini
model-tier: fast
---
# Content
"""
    fm = parse_skill_frontmatter(content_kebab, "summarizer_skill")
    assert fm.specialized_model == "gpt-4o-mini"
    assert fm.model_tier == "fast"


def test_default_empty_specialized_model_contract() -> None:
    content_default = """---
description: Standard general purpose skill without specialized model declaration
---
# Content
"""
    fm = parse_skill_frontmatter(content_default, "general_skill")
    assert fm.specialized_model is None
    assert fm.model_tier is None

    metadata = build_skill_metadata(
        skill_name="general_skill",
        frontmatter=fm,
        storage_path="/tmp/general",
        content=content_default,
        trust=SkillTrust.TRUSTED,
    )
    assert metadata.specialized_model is None
    assert metadata.model_tier is None
