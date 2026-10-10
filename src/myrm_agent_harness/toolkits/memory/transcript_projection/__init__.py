"""SQLite transcript projection and adoption disambiguation suite.

[INPUT]
- models.py, adoption_engine.py, projection_store.py components.

[OUTPUT]
- TranscriptAdoptionEngine, SqliteTranscriptProjectionStore, and domain models.

[POS]
- Facade package for Item 150 SqliteTranscriptProjectionSuite.
"""

from __future__ import annotations

from .adoption_engine import TranscriptAdoptionEngine
from .models import (
    AdoptionDecision,
    AdoptionStatus,
    BootstrapContext,
    BootstrapResult,
    SessionMessage,
    TranscriptEntry,
)
from .projection_store import SqliteTranscriptProjectionStore

__all__ = [
    "AdoptionDecision",
    "AdoptionStatus",
    "BootstrapContext",
    "BootstrapResult",
    "SessionMessage",
    "SqliteTranscriptProjectionStore",
    "TranscriptAdoptionEngine",
    "TranscriptEntry",
]
