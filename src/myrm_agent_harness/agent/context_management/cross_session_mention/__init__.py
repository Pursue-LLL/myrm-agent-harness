# [INPUT]: None
# [OUTPUT]: CrossSessionConfig, CrossSessionMentionReferenceAndSnapshotInjectionSuite, MentionInjectionResult, SessionMentionParser, SessionMentionTag, SessionRecord, SessionSnapshot, SessionSnapshotExtractor
# [POS]: agent/context_management/cross_session_mention/__init__.py

"""Public contracts and facade for cross-session @ mention referencing and read-only snapshot injection.

[INPUT]
- None (Facade exports).

[OUTPUT]
- CrossSessionConfig: Configuration parameters and capacity limits.
- SessionRecord: Historical session entity.
- SessionMentionTag: Parsed @Session reference tag.
- SessionSnapshot: Distilled immutable read-only snapshot.
- MentionInjectionResult: Container holding enriched user prompt, snapshots, and proof badges.
- SessionMentionParser: Tag detector and identifier matching engine.
- SessionSnapshotExtractor: Safe, read-only snapshot extractor.
- CrossSessionMentionReferenceAndSnapshotInjectionSuite: Unified end-to-end facade.

[POS]
Modular subpackage in context management establishing DeepSeek Harness inspired cross-session referencing.
"""

from __future__ import annotations

from .cross_session_mention_suite import (
    CrossSessionMentionReferenceAndSnapshotInjectionSuite,
)
from .cross_session_types import (
    CrossSessionConfig,
    MentionInjectionResult,
    SessionMentionTag,
    SessionRecord,
    SessionSnapshot,
)
from .session_mention_parser import SessionMentionParser
from .session_snapshot_extractor import SessionSnapshotExtractor

__all__ = [
    "CrossSessionConfig",
    "CrossSessionMentionReferenceAndSnapshotInjectionSuite",
    "MentionInjectionResult",
    "SessionMentionParser",
    "SessionMentionTag",
    "SessionRecord",
    "SessionSnapshot",
    "SessionSnapshotExtractor",
]
