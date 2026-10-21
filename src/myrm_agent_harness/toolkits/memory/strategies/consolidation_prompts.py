"""System and user prompts for cross-session memory consolidation.

[INPUT]
- memory.types::AnyMemory (POS: memory data models)

[OUTPUT]
- _SYSTEM_PROMPT: Base system instructions for memory consolidation
- _build_user_prompt: Serializes memories to compact user prompt with short IDs
- _build_id_map: Maps compact short IDs to full UUIDs

[POS]
Prompts and payload compression helpers for memory consolidation.
Enforces Class-First Rubric and preserves Prompt Cache static prefixes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.types import AnyMemory

_SYSTEM_PROMPT = """You are a memory consolidation agent. Analyze the user's memories (semantic facts, episodic events, and procedural rules) and identify:

1. **Contradictions**: Memories that conflict (e.g., "prefers Python" vs "prefers Rust")
2. **Redundancies**: Multiple memories expressing the same fact → merge into one
3. **Date conversion**: Relative dates ("yesterday", "last week") → absolute dates (YYYY-MM-DD)
4. **Enrichment**: Fragmented memories that can be combined into a richer single memory
5. **Stale corrections**: When multiple corrections exist on the same topic (indicated by `corrects:` or similar `source_error`), keep the newest correction and demote older ones via update_content (set importance to 0.05)

## Rubric (Class-First 评分标准)
Before proposing any consolidation operation, strictly evaluate it against these dimensions:
1. **准确性 (Accuracy)**: Does the merged/updated memory accurately reflect the underlying truth without hallucination?
2. **防碎片化 (Anti-fragmentation)**: Does this operation combine fragmented pieces into a cohesive, complete whole?
3. **冗余度 (Redundancy)**: Does this operation successfully eliminate duplicate or overlapping information?

## Rules
- Only output actions when there is clear evidence. Do NOT fabricate connections.
- Preserve all unique information when merging. Never discard details.
- Use absolute dates based on today's date provided below.
- Keep the original language (Chinese stays Chinese, English stays English).
- For procedural rules (type=procedural), use ONLY update_content (NOT merge or correct, since rules have structured trigger/action fields).
- Memories tagged [NEW] are recently added. Pay special attention to contradictions between [NEW] and existing memories.

## Output
Output a structured JSON object containing `operations` and `insights`.
"""


def _build_user_prompt(
    memories: Sequence[AnyMemory],
    today: str,
    id_map: dict[str, str],
    new_ids: frozenset[str] | None = None,
) -> str:
    """Build user prompt with short IDs to save tokens (~28 tokens per memory)."""
    reverse_map = {v: k for k, v in id_map.items()}
    lines = [f"Today's date: {today}", "", "## Memories to analyze", ""]
    for mem in memories:
        short_id = reverse_map.get(mem.id, mem.id[:8])
        tag = " [NEW]" if new_ids and mem.id in new_ids else ""
        meta_parts = [f"type={mem.memory_type}"]
        if hasattr(mem, "importance"):
            meta_parts.append(f"importance={mem.importance:.1f}")
        if hasattr(mem, "confidence"):
            meta_parts.append(f"confidence={mem.confidence:.1f}")
        meta_parts.append(f"created={mem.created_at.strftime('%Y-%m-%d %H:%M')}")
        correction_of = getattr(mem, "correction_of", None)
        if correction_of:
            corrects_short = reverse_map.get(correction_of, correction_of[:8])
            meta_parts.append(f"corrects:{corrects_short}")
        lines.append(f"[{short_id}]{tag} ({', '.join(meta_parts)})")
        if hasattr(mem, "trigger") and hasattr(mem, "action"):
            lines.append(f"  trigger: {mem.trigger}")
            lines.append(f"  action: {mem.action}")
        else:
            lines.append(f"  {mem.content}")
        source_error = getattr(mem, "source_error", None)
        if source_error:
            lines.append(f"  source_error: {source_error}")
        lines.append("")
    lines.append("Analyze these memories and output a JSON object with operations and insights.")
    return "\n".join(lines)


def _build_id_map(memories: Sequence[AnyMemory]) -> dict[str, str]:
    """Build short_id → full_id mapping. Uses first 8 chars, extends on collision."""
    id_map: dict[str, str] = {}
    used_shorts: set[str] = set()
    for mem in memories:
        short = mem.id[:8]
        length = 8
        while short in used_shorts and length < len(mem.id):
            length += 4
            short = mem.id[:length]
        id_map[short] = mem.id
        used_shorts.add(short)
    return id_map


__all__ = [
    "_SYSTEM_PROMPT",
    "_build_id_map",
    "_build_user_prompt",
]
