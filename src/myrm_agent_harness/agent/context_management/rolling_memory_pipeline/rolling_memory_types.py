# [INPUT]: None
# [OUTPUT]: ChunkProcessingStep, ChunkStreamConfig, RollingPipelineResult, RollingWorkingMemory, TextChunk
# [POS]: agent/context_management/rolling_memory_pipeline/rolling_memory_types.py

"""Domain models and contracts for chunk-bounded rolling working memory and long-context comprehension.

[INPUT]
- None (Self-contained domain definitions inspired by Uni-Agent MemAgent).

[OUTPUT]
- ChunkStreamConfig: Tunable token budgets, overlaps, and memory ceilings.
- TextChunk: Sliced text segment with token estimation and byte boundary metadata.
- RollingWorkingMemory: Compact, structured state carried across chunk transitions.
- ChunkProcessingStep: Audit trace of a single chunk absorption and memory update.
- RollingPipelineResult: Complete end-to-end outcome including final memory and synthesized deck.

[POS]
Domain layer establishing MemAgent inspired rolling memory architecture for edge and small LLMs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class ChunkStreamConfig:
    """Settings governing chunk sizing and memory carry-over caps."""

    chunk_token_budget: int = 4000
    overlap_tokens: int = 200
    max_memory_tokens: int = 1500
    agent_scope_id: str = "default_agent"


@dataclass(frozen=True)
class TextChunk:
    """Individual bounded slice of a large document with positional offsets."""

    chunk_index: int
    total_chunks: int
    text_content: str
    token_estimate: int
    char_offset_start: int
    char_offset_end: int


@dataclass(frozen=True)
class RollingWorkingMemory:
    """Compact state distilled from chunks and rolled forward to subsequent clean contexts."""

    step_index: int
    core_thesis: str
    key_entities: Sequence[str] = field(default_factory=tuple)
    timeline_or_events: Sequence[str] = field(default_factory=tuple)
    unresolved_questions: Sequence[str] = field(default_factory=tuple)
    token_estimate: int = 0
    agent_scope_id: str = "default_agent"


@dataclass(frozen=True)
class ChunkProcessingStep:
    """Step record documenting memory progression across a specific chunk."""

    chunk_index: int
    input_chunk_tokens: int
    memory_before: RollingWorkingMemory | None
    memory_after: RollingWorkingMemory
    duration_ms: float = 0.0


@dataclass(frozen=True)
class RollingPipelineResult:
    """Consolidated outcome of processing a massive document via bounded rolling memory."""

    total_source_tokens: int
    chunks_processed: int
    final_memory: RollingWorkingMemory
    history_steps: Sequence[ChunkProcessingStep]
    synthesized_artifact_markdown: str
