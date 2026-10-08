"""Public contracts and facade for chunk-bounded rolling working memory and long-context comprehension.

[INPUT]
- None (Facade exports).

[OUTPUT]
- ChunkBoundedRollingMemoryAgentPipelineSuite: Top-level unified pipeline suite.
- ChunkProcessingStep: Step transition record.
- ChunkStreamConfig: Token budget and memory configuration.
- RollingPipelineResult: Outcome container with final memory and artifact markdown.
- RollingWorkingMemory: Compact state passed across clean model contexts.
- RollingWorkingMemoryStateMachine: Memory state machine advancing across chunks.
- TextChunk: Sliced text segment.
- TokenBoundedChunkStreamer: Natural paragraph chunk streamer.

[POS]
Modular subpackage in agent/context_management establishing Uni-Agent MemAgent architecture.
"""

from __future__ import annotations

from .chunk_bounded_rolling_memory_pipeline_suite import (
    ChunkBoundedRollingMemoryAgentPipelineSuite,
)
from .rolling_memory_state_machine import RollingWorkingMemoryStateMachine
from .rolling_memory_types import (
    ChunkProcessingStep,
    ChunkStreamConfig,
    RollingPipelineResult,
    RollingWorkingMemory,
    TextChunk,
)
from .token_bounded_chunk_streamer import TokenBoundedChunkStreamer

__all__ = [
    "ChunkBoundedRollingMemoryAgentPipelineSuite",
    "ChunkProcessingStep",
    "ChunkStreamConfig",
    "RollingPipelineResult",
    "RollingWorkingMemory",
    "RollingWorkingMemoryStateMachine",
    "TextChunk",
    "TokenBoundedChunkStreamer",
]
