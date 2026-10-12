"""Pitfall memory factory — validated EpisodicMemory for cross-task trap prevention.

[INPUT]
- memory.types::EpisodicMemory (POS: Memory type system foundation. Provides type-safe schema definitions for all memory types.)

[OUTPUT]
- create_pitfall_memory: Factory building a failure-attempt EpisodicMemory with enforced non-empty cause and lesson

[POS]
Deterministic factory in memory/strategies. Guarantees consistent failure metadata for
context rendering firewalls and deduplication pipelines.
"""

from __future__ import annotations

from typing import Literal

from myrm_agent_harness.toolkits.memory.types import EpisodicMemory

__all__ = ["create_pitfall_memory"]


def create_pitfall_memory(
    *,
    content: str,
    failure_reason: str,
    negative_lesson: str,
    subtask_phase: Literal["analyze", "locate", "edit", "verify"] | None = None,
    confidence_tier: Literal["strong", "weak", "shadow"] = "strong",
    relation_category: Literal["same_work_item", "same_problem", "reusable_sop", "shadow_context"] = "same_problem",
    importance: float = 0.8,
    language: Literal["zh", "en"] = "en",
    related_entities: list[str] | None = None,
    source_chat_id: str | None = None,
    source_message_id: str | None = None,
) -> EpisodicMemory:
    """Factory creating a well-formed pitfall EpisodicMemory for cross-task trap prevention.

    Enforces non-empty failure cause and negative guidance, ensuring consistent metadata
    for context rendering firewalls and deduplication pipelines.

    Args:
        content: Detailed summary of what went wrong.
        failure_reason: Concise, structured description of the root failure cause.
        negative_lesson: Actionable negative rule to prevent repeating this failure.
        subtask_phase: Optional phase where this failure occurred.
        confidence_tier: Reusability tier ('strong' drives action, 'weak'/'shadow' is reference only).
        relation_category: Relationship classification (defaults to 'same_problem').
        importance: Priority score between 0.0 and 1.0 (defaults to high 0.8 for pitfalls).
        language: Language of the memory text.
        related_entities: Optional entity symbols associated with this trap.
        source_chat_id: Source session identifier.
        source_message_id: Source turn identifier.

    Returns:
        Validated EpisodicMemory instance with is_failure_attempt=True.

    Raises:
        ValueError: If content, failure_reason, or negative_lesson are empty or purely whitespace.
    """
    clean_content = content.strip()
    if not clean_content:
        raise ValueError("Pitfall memory 'content' must not be empty.")

    clean_reason = failure_reason.strip()
    if not clean_reason:
        raise ValueError("Pitfall memory 'failure_reason' must not be empty.")

    clean_lesson = negative_lesson.strip()
    if not clean_lesson:
        raise ValueError("Pitfall memory 'negative_lesson' must not be empty.")

    clamped_importance = max(0.0, min(1.0, float(importance)))

    return EpisodicMemory(
        content=clean_content,
        is_failure_attempt=True,
        failure_reason=clean_reason,
        negative_lesson=clean_lesson,
        subtask_phase=subtask_phase,
        confidence_tier=confidence_tier,
        relation_category=relation_category,
        importance=clamped_importance,
        language=language,
        related_entities=list(related_entities or []),
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
    )
