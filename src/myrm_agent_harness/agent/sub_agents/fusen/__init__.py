"""Lightweight Fusen Shared State Sync package (Item 63).

[INPUT]
- Subagent coordination signals and micro-blockers.

[OUTPUT]
- Exported classes and enums for Fusen sticky-note board.

[POS]
- Shared state board eliminating LLM token overhead in multi-agent swarm coordination.
"""

from __future__ import annotations

from .fusen_board import FusenSharedBoard
from .types import (
    FusenBlockerSummary,
    FusenCategory,
    FusenNote,
    NoteStatus,
)

__all__ = [
    "FusenBlockerSummary",
    "FusenCategory",
    "FusenNote",
    "FusenSharedBoard",
    "NoteStatus",
]
