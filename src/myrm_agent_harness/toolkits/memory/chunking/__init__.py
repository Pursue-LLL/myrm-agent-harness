"""Incremental sliding window Markdown chunking package.

[POS]
Embedded package providing semantic sliding window slicing, boundary protection,
deterministic chunk hashing, incremental diff indexing, and context hydration.

[INPUT]
- .models (ChunkingConfig, IncrementalDiffReport, MarkdownChunk)
- .chunker (MarkdownSlidingWindowChunker)
- .pipeline (IncrementalIndexingPipeline)
- .hydrator (ChunkSourceHydrator)

[OUTPUT]
- ChunkSourceHydrator, ChunkingConfig, IncrementalDiffReport
- IncrementalIndexingPipeline, MarkdownChunk, MarkdownSlidingWindowChunker
"""

from myrm_agent_harness.toolkits.memory.chunking.chunker import (
    MarkdownSlidingWindowChunker,
)
from myrm_agent_harness.toolkits.memory.chunking.conversation import (
    ChunkingStrategy,
    ConversationChunk,
    ConversationEpisode,
    EpisodesChunker,
    _parse_message_timestamp,
    chunk_conversation,
)
from myrm_agent_harness.toolkits.memory.chunking.hydrator import (
    ChunkSourceHydrator,
)
from myrm_agent_harness.toolkits.memory.chunking.models import (
    ChunkingConfig,
    IncrementalDiffReport,
    MarkdownChunk,
)
from myrm_agent_harness.toolkits.memory.chunking.pipeline import (
    IncrementalIndexingPipeline,
)

__all__ = [
    "ChunkSourceHydrator",
    "ChunkingConfig",
    "ChunkingStrategy",
    "ConversationChunk",
    "ConversationEpisode",
    "EpisodesChunker",
    "IncrementalDiffReport",
    "IncrementalIndexingPipeline",
    "MarkdownChunk",
    "MarkdownSlidingWindowChunker",
    "_parse_message_timestamp",
    "chunk_conversation",
]
