"""State machine managing rolling working memory progression across sequential document chunks.

[INPUT]
- ChunkStreamConfig: Memory token budgets and agent scoping.
- TextChunk: Input chunk to ingest.
- RollingWorkingMemory: Prior state carrying historical knowledge forward.

[OUTPUT]
- RollingWorkingMemoryStateMachine: Pure state transition engine updating compact memory per chunk.

[POS]
Memory state transition and condensation engine in MemAgent architecture.
"""

from __future__ import annotations

import re
from typing import Callable, Sequence

from .rolling_memory_types import ChunkStreamConfig, RollingWorkingMemory, TextChunk


class RollingWorkingMemoryStateMachine:
    """Carries compact working memory forward across chunks while keeping per-chunk context light."""

    def __init__(self, config: ChunkStreamConfig | None = None) -> None:
        self._config = config or ChunkStreamConfig()

    def build_step_prompt(
        self,
        previous_memory: RollingWorkingMemory | None,
        chunk: TextChunk,
    ) -> str:
        """Constructs a clean minimal prompt for an LLM to digest chunk and update working memory."""
        prompt_lines: list[str] = [
            f"[MEMAGENT RUNTIME: CHUNK {chunk.chunk_index} OF {chunk.total_chunks}]",
            "Task: Absorb the chunk below, integrate with prior working memory, and produce an updated compact summary.",
        ]

        if previous_memory and previous_memory.core_thesis:
            prompt_lines.extend(
                [
                    "\n--- PRIOR WORKING MEMORY ---",
                    f"Core Thesis: {previous_memory.core_thesis}",
                    f"Key Entities: {', '.join(previous_memory.key_entities)}",
                    f"Established Timeline/Events: {len(previous_memory.timeline_or_events)} items",
                    "----------------------------",
                ]
            )
        else:
            prompt_lines.append("\n(No prior working memory; this is the initial document chunk.)")

        prompt_lines.extend(
            [
                f"\n--- CURRENT CHUNK TEXT (Tokens ~{chunk.token_estimate}) ---",
                chunk.text_content,
                "--------------------------------------------------",
                "\nUpdate the working memory concisely (max 1500 tokens).",
            ]
        )
        return "\n".join(prompt_lines)

    def advance(
        self,
        previous_memory: RollingWorkingMemory | None,
        chunk: TextChunk,
        custom_extractor: (
            Callable[[RollingWorkingMemory | None, TextChunk], RollingWorkingMemory] | None
        ) = None,
    ) -> RollingWorkingMemory:
        """Transitions state forward by absorbing current chunk into new RollingWorkingMemory."""
        if custom_extractor is not None:
            return custom_extractor(previous_memory, chunk)

        # Built-in deterministic extraction engine
        return self._deterministic_update(previous_memory, chunk)

    def _deterministic_update(
        self,
        previous_memory: RollingWorkingMemory | None,
        chunk: TextChunk,
    ) -> RollingWorkingMemory:
        """Extracts structured thesis, entities, and events deterministically without LLM dependency."""
        lines = [line.strip() for line in chunk.text_content.splitlines() if line.strip()]

        # 1. Core thesis synthesis
        new_thesis = previous_memory.core_thesis if previous_memory else ""
        if not new_thesis and lines:
            # First meaningful heading or line
            heading_cand = next((l for l in lines if l.startswith("#")), lines[0])
            new_thesis = re.sub(r"^#+\s*", "", heading_cand)

        # 2. Extract capitalized entity words or key terms
        found_entities: set[str] = set(previous_memory.key_entities if previous_memory else ())
        for line in lines[:30]:
            # Extract PascalCase or UPPERCASE tokens of length >= 3
            tokens = re.findall(r"\b[A-Z][a-zA-Z0-9_\-]{2,}\b", line)
            for t in tokens:
                if len(t) < 30:
                    found_entities.add(t)

        # 3. Extract events / bullet items
        events: list[str] = list(previous_memory.timeline_or_events if previous_memory else ())
        for line in lines:
            if line.startswith(("-", "*", "1.", "2.", "3.", "4.", "5.")) or "step" in line.lower():
                clean_item = re.sub(r"^[-*+]|\d+\.\s*", "", line).strip()
                if clean_item and clean_item not in events:
                    events.append(clean_item)

        # 4. Token budgeting & condensation
        entities_list = sorted(list(found_entities))[:40]
        max_events = 25
        trimmed_events = events[-max_events:] if len(events) > max_events else events

        raw_summary = (
            f"Thesis: {new_thesis}\n"
            f"Entities: {', '.join(entities_list)}\n"
            f"Events:\n" + "\n".join(f"- {e}" for e in trimmed_events)
        )
        token_estimate = max(1, (len(raw_summary) + 3) // 4)

        step_idx = (previous_memory.step_index + 1) if previous_memory else 1

        return RollingWorkingMemory(
            step_index=step_idx,
            core_thesis=new_thesis,
            key_entities=tuple(entities_list),
            timeline_or_events=tuple(trimmed_events),
            unresolved_questions=previous_memory.unresolved_questions if previous_memory else (),
            token_estimate=token_estimate,
            agent_scope_id=self._config.agent_scope_id,
        )
