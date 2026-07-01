"""Stable skill metadata utilities for product skill management.

Re-exports frontmatter parsing and metadata builders so consumers never import
private ``backends.skills._*`` modules directly.
"""

from __future__ import annotations

from myrm_agent_harness.backends.skills._runtime import (
    build_skill_metadata,
    compute_content_hash,
)
from myrm_agent_harness.backends.skills._utils import (
    SkillMetadataError,
    parse_skill_frontmatter,
    update_frontmatter_evolution_lock,
)

__all__ = [
    "SkillMetadataError",
    "build_skill_metadata",
    "compute_content_hash",
    "parse_skill_frontmatter",
    "update_frontmatter_evolution_lock",
]
