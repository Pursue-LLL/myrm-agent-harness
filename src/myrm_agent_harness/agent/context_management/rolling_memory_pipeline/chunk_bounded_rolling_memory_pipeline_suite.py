# [INPUT]: ChunkProcessingStep, ChunkStreamConfig, RollingPipelineResult, RollingWorkingMemory, TextChunk, RollingWorkingMemoryStateMachine, TokenBoundedChunkStreamer
# [OUTPUT]: ChunkBoundedRollingMemoryAgentPipelineSuite
# [POS]: agent/context_management/rolling_memory_pipeline/chunk_bounded_rolling_memory_pipeline_suite.py

"""End-to-end facade orchestrating token-bounded document streaming, rolling memory evolution, and artifact generation.

[INPUT]
- Domain types: ChunkProcessingStep, ChunkStreamConfig, RollingPipelineResult, RollingWorkingMemory, TextChunk.
- Engines: TokenBoundedChunkStreamer, RollingWorkingMemoryStateMachine.

[OUTPUT]
- ChunkBoundedRollingMemoryAgentPipelineSuite: Unified facade suite for long-context comprehension on edge models.

[POS]
Main entry point and orchestrator in agent/context_management/rolling_memory_pipeline implementing MemAgent.
"""

from __future__ import annotations

import time
from typing import Callable, Sequence

from .rolling_memory_state_machine import RollingWorkingMemoryStateMachine
from .rolling_memory_types import (
    ChunkProcessingStep,
    ChunkStreamConfig,
    RollingPipelineResult,
    RollingWorkingMemory,
    TextChunk,
)
from .token_bounded_chunk_streamer import TokenBoundedChunkStreamer


class ChunkBoundedRollingMemoryAgentPipelineSuite:
    """Unified pipeline reading massive text in token-bounded chunks and rolling compact state forward."""

    def __init__(
        self,
        config: ChunkStreamConfig | None = None,
        streamer: TokenBoundedChunkStreamer | None = None,
        state_machine: RollingWorkingMemoryStateMachine | None = None,
    ) -> None:
        self._config = config or ChunkStreamConfig()
        self._streamer = streamer or TokenBoundedChunkStreamer(self._config)
        self._state_machine = state_machine or RollingWorkingMemoryStateMachine(self._config)

    @property
    def config(self) -> ChunkStreamConfig:
        return self._config

    def stream_and_process(
        self,
        text: str,
        custom_extractor: (
            Callable[[RollingWorkingMemory | None, TextChunk], RollingWorkingMemory] | None
        ) = None,
    ) -> RollingPipelineResult:
        """Executes full streaming and rolling memory progression over source text."""
        chunks = self._streamer.stream_chunks(text)
        if not chunks:
            empty_memory = RollingWorkingMemory(
                step_index=0,
                core_thesis="(Empty Document)",
                agent_scope_id=self._config.agent_scope_id,
            )
            return RollingPipelineResult(
                total_source_tokens=0,
                chunks_processed=0,
                final_memory=empty_memory,
                history_steps=(),
                synthesized_artifact_markdown=self.generate_artifact_deck(empty_memory, ()),
            )

        current_memory: RollingWorkingMemory | None = None
        history_steps: list[ChunkProcessingStep] = []
        total_source_tokens = sum(c.token_estimate for c in chunks)

        for chunk in chunks:
            t0 = time.perf_counter()
            next_memory = self._state_machine.advance(
                previous_memory=current_memory,
                chunk=chunk,
                custom_extractor=custom_extractor,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            step_record = ChunkProcessingStep(
                chunk_index=chunk.chunk_index,
                input_chunk_tokens=chunk.token_estimate,
                memory_before=current_memory,
                memory_after=next_memory,
                duration_ms=elapsed_ms,
            )
            history_steps.append(step_record)
            current_memory = next_memory

        assert current_memory is not None
        deck = self.generate_artifact_deck(current_memory, chunks)

        return RollingPipelineResult(
            total_source_tokens=total_source_tokens,
            chunks_processed=len(chunks),
            final_memory=current_memory,
            history_steps=tuple(history_steps),
            synthesized_artifact_markdown=deck,
        )

    def generate_artifact_deck(
        self,
        final_memory: RollingWorkingMemory,
        chunks: Sequence[TextChunk],
    ) -> str:
        """Renders comprehensive Markdown artifact deck summarizing document cognition and navigation."""
        lines: list[str] = [
            f"# Document Cognition Deck: {final_memory.core_thesis or 'Untitled Analysis'}",
            "",
            "## Processing Metrics",
            f"- **Agent Scope**: `{final_memory.agent_scope_id}`",
            f"- **Total Chunks Sliced**: `{len(chunks)}`",
            f"- **Final Memory Footprint**: `{final_memory.token_estimate}` tokens",
            "",
            "## Core Thesis & Findings",
            final_memory.core_thesis or "(No thesis statement identified)",
            "",
            "## Key Entities & Concepts",
        ]

        if final_memory.key_entities:
            lines.append(", ".join(f"`{e}`" for e in final_memory.key_entities))
        else:
            lines.append("*(None extracted)*")

        lines.extend(["", "## Progression Timeline & Key Events"])
        if final_memory.timeline_or_events:
            for ev in final_memory.timeline_or_events:
                lines.append(f"- {ev}")
        else:
            lines.append("*(No sequential milestones recorded)*")

        lines.extend(["", "## Chunk Navigation Index"])
        for c in chunks:
            lines.append(
                f"- **Chunk {c.chunk_index}/{c.total_chunks}** (Offset: {c.char_offset_start}..{c.char_offset_end}, ~{c.token_estimate} tokens)"
            )

        return "\n".join(lines)
