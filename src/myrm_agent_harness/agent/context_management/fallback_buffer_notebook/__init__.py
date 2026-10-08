"""Auto-Compact Fallback Buffer and Team Notebook Suite (Item 223).

Exports contracts and the core engine for token headroom reserve buffers,
shared multi-agent scratchpads, and transparent compaction consequence banners.

[INPUT]
- agent.context_management.fallback_buffer_notebook.fallback_buffer_engine::FallbackBufferNotebookEngine (POS:
  Core engine for Auto-Compact Fallback Buffer and Team Notebook Suite (Item 223).)
- agent.context_management.fallback_buffer_notebook.fallback_buffer_types::BufferWatermarkSnapshot,
  BufferWatermarkState, CompactionConsequenceAlert, FallbackBufferConfig, TeamNotebookEntry,
  TeamNotebookSnapshot (POS: Strongly typed contracts for Auto-Compact Fallback Buffer and Team Notebook Suite
  (Item 223).)

[OUTPUT]
- Re-exports: BufferWatermarkSnapshot, BufferWatermarkState, CompactionConsequenceAlert, FallbackBufferConfig,
  FallbackBufferNotebookEngine, TeamNotebookEntry, TeamNotebookSnapshot

[POS]
Auto-Compact Fallback Buffer and Team Notebook Suite (Item 223).
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
