"""Stable skill metadata utilities for product skill management.

[INPUT]
- myrm_agent_harness.backends.skills._runtime (POS: skill metadata builder and content hash)
- myrm_agent_harness.backends.skills._utils (POS: SKILL.md frontmatter parser)

[OUTPUT]
- SkillMetadataError, parse_skill_frontmatter, update_frontmatter_evolution_lock,
  compute_content_hash, build_skill_metadata

[POS]
Public re-export facade. Product skill CRUD/sync code imports here instead of
private ``backends.skills._*`` modules.
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
