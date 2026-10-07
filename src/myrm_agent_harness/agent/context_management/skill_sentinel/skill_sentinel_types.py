"""Type definitions for Active Skill Compaction Survival Sentinel and Reattachment Governor.

Provides immutable data contracts for active skill lifecycle tracking, single skill (5k)
and total combined (25k) token budgets, and post-compaction SOP reattachment.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActiveSkillRecord:
    """Immutable record of an activated skill within a conversation session."""

    skill_name: str
    invoked_turn_index: int
    content_hash: str
    instruction_body: str
    estimated_tokens: int
    last_accessed_turn: int
    is_pinned: bool = False
    drift_detected: bool = False


@dataclass(frozen=True)
class SkillBudgetPolicy:
    """Token budget constraints modeled after production-grade skill compaction practices."""

    max_single_skill_tokens: int = 5000
    max_total_reattached_tokens: int = 25000


@dataclass(frozen=True)
class ReattachedSkillBlock:
    """Rendered skill SOP block re-attached after compaction."""

    skill_name: str
    truncated: bool
    tokens_used: int
    rendered_content: str


@dataclass(frozen=True)
class ReattachmentResult:
    """Result of post-compaction skill re-attachment governance."""

    session_id: str
    turn_index: int
    reattached_skills: tuple[ReattachedSkillBlock, ...]
    dropped_skills: tuple[str, ...]
    total_reattached_tokens: int
    injected_tag: str
