"""Wiki vs memory write boundary helpers.

Hard guard for memory_save when wiki corpus is enabled, and shared heuristics
for auto-extraction prompts.

[INPUT]
- (none — pure heuristics and counters)

[OUTPUT]
- looks_like_wiki_document: Heuristic for document-like memory_save payloads.
- wiki_memory_save_rejection_message: Rejection message (optional GUI tool hint).
- filter_wiki_document_vector_memories: Drop document-like semantic/episodic before persist.
- record_wiki_memory_save_rejection / get_wiki_memory_save_rejection_count: Guard metrics.

[POS]
Wiki-memory write boundary heuristics. Keeps long-form knowledge out of semantic memory when wiki is enabled.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.types import AnyMemory

logger = logging.getLogger(__name__)

WIKI_MEMORY_SAVE_MAX_CHARS = 800
WIKI_MEMORY_SAVE_MIN_HEADINGS = 3

_HEADING_PATTERN = re.compile(r"^#{1,6}\s", re.MULTILINE)

_rejection_lock = threading.Lock()
_wiki_memory_save_rejections = 0


def looks_like_wiki_document(content: str) -> bool:
    """Return True when content looks like a document rather than a compact memory fact."""
    stripped = content.strip()
    if not stripped:
        return False
    if len(stripped) >= WIKI_MEMORY_SAVE_MAX_CHARS:
        return True
    return len(_HEADING_PATTERN.findall(stripped)) >= WIKI_MEMORY_SAVE_MIN_HEADINGS


def wiki_memory_save_rejection_message(*, include_tool_hint: bool = True) -> str:
    """Rejection message for document-like memory payloads.

    ``include_tool_hint=False`` drops the GUI-only ``wiki_ingest_tool``
    reference for surfaces (e.g. MCP) that do not expose that tool.
    """
    if not include_tool_hint:
        return (
            "Rejected: content looks like a document, not a compact memory entry. "
            "Long-form articles, notes, or reference text are not appropriate for "
            "memory. Memory is for short durable facts (preferences, constraints, profile)."
        )
    return (
        "Rejected: content looks like a document, not a compact memory entry. "
        "Use wiki_ingest_tool to add articles, notes, or long reference text to the knowledge base. "
        "Memory is for short durable facts (preferences, constraints, profile)."
    )


def record_wiki_memory_save_rejection() -> int:
    """Increment rejection counter and return the new total."""
    global _wiki_memory_save_rejections
    with _rejection_lock:
        _wiki_memory_save_rejections += 1
        total = _wiki_memory_save_rejections
    logger.info("wiki_memory_save_rejected total=%d", total)
    return total


def get_wiki_memory_save_rejection_count() -> int:
    with _rejection_lock:
        return _wiki_memory_save_rejections


def reset_wiki_memory_save_rejection_count() -> None:
    global _wiki_memory_save_rejections
    with _rejection_lock:
        _wiki_memory_save_rejections = 0


def filter_wiki_document_vector_memories(
    memories: list[AnyMemory],
    *,
    enabled: bool,
) -> tuple[list[AnyMemory], int]:
    """Drop document-like semantic/episodic memories when wiki boundary is enabled."""
    from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

    if not enabled or not memories:
        return memories, 0

    kept: list[AnyMemory] = []
    dropped = 0
    for mem in memories:
        if isinstance(
            mem, (SemanticMemory, EpisodicMemory)
        ) and looks_like_wiki_document(mem.content):
            dropped += 1
            continue
        kept.append(mem)

    if dropped:
        logger.info("wiki_extract_memory_filtered dropped=%d", dropped)
    return kept, dropped
