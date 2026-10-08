"""Intake gatekeeper and prompt formatter for Dual-Layer Profile & Working Notes.

[INPUT]
- Sequence[AnyMemory]: candidate memory records to ingest into persistence
- str user_profile, str agent_notes: raw text content for dual layers

[OUTPUT]
- filter_intake_garbage: batch filter stripping out ephemeral noise
- check_memory_not_garbage: single-memory validator raising MemoryError on transient noise
- format_profile_notes_prompt_section: system prompt injection assembler

[POS]
Harness toolkit memory governance component bridging Hermes memory guidelines
(USER <= 1375c, MEMORY <= 2200c) with the execution runtime and write pipeline.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.profile_notes.garbage_filter import (
    MemoryIntakeGarbageFilter,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.types import AnyMemory

logger = logging.getLogger(__name__)

_DEFAULT_FILTER = MemoryIntakeGarbageFilter(strict_mode=True)


def check_memory_not_garbage(memory: AnyMemory) -> None:
    """Validate that candidate memory does not contain transient or ephemeral noise.

    Raises:
        MemoryError: If content matches task progress, ephemeral IDs, errors, or relative time.
    """
    content = getattr(memory, "content", "")
    if not isinstance(content, str) or not content.strip():
        return

    decision = _DEFAULT_FILTER.evaluate_intake(content)
    if not decision.accepted:
        from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError

        reason = decision.rejected_reason or "Ephemeral noise rejected by intake filter"
        raise MemoryError(f"Memory intake rejected: {reason}")


def filter_intake_garbage(memories: Sequence[AnyMemory]) -> tuple[list[AnyMemory], int]:
    """Filter candidate memory batch, removing transient garbage records.

    Returns:
        A tuple of (accepted_memories, dropped_count).
    """
    accepted: list[AnyMemory] = []
    dropped = 0

    for mem in memories:
        content = getattr(mem, "content", "")
        if not isinstance(content, str) or not content.strip():
            accepted.append(mem)
            continue

        decision = _DEFAULT_FILTER.evaluate_intake(content)
        if decision.accepted:
            accepted.append(mem)
        else:
            dropped += 1
            logger.info(
                "Memory intake garbage filter dropped transient noise (%s): %s",
                decision.garbage_category,
                decision.rejected_reason,
            )

    return accepted, dropped


def format_profile_notes_prompt_section(user_profile: str, agent_notes: str) -> str:
    """Assemble structured dual-layer profile and notes into a prompt injection block.

    Args:
        user_profile: Long-term user preferences, persona habits, and constraints.
        agent_notes: Domain architecture conventions, project guidelines, and operational notes.

    Returns:
        Formatted markdown block suitable for SystemMessage injection.
    """
    sections: list[str] = []
    clean_profile = user_profile.strip()
    clean_notes = agent_notes.strip()

    if clean_profile:
        sections.append(f"## User Profile (Long-Term Preferences)\n{clean_profile}")
    if clean_notes:
        sections.append(f"## Agent Working Notes (Domain & Project Conventions)\n{clean_notes}")

    if not sections:
        return ""

    return "\n\n".join(sections)
