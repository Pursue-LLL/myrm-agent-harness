"""Auto-Compact Fallback Buffer and Team Notebook Suite (Item 223).

Exports contracts and the core engine for token headroom reserve buffers,
shared multi-agent scratchpads, and transparent compaction consequence banners.
"""

from __future__ import annotations

from .fallback_buffer_engine import FallbackBufferNotebookEngine
from .fallback_buffer_types import (
    BufferWatermarkSnapshot,
    BufferWatermarkState,
    CompactionConsequenceAlert,
    FallbackBufferConfig,
    TeamNotebookEntry,
    TeamNotebookSnapshot,
)

__all__ = [
    "BufferWatermarkSnapshot",
    "BufferWatermarkState",
    "CompactionConsequenceAlert",
    "FallbackBufferConfig",
    "FallbackBufferNotebookEngine",
    "TeamNotebookEntry",
    "TeamNotebookSnapshot",
]
