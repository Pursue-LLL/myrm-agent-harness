"""Session display renaming via metadata.name and title precedence arbitration package.

[INPUT]
- agent.context_management.session_metadata_rename.metadata_name_resolver::normalize_session_display_title,
  resolve_session_display_title (POS: Functional normalizer and precedence resolver.)
- agent.context_management.session_metadata_rename.metadata_rename_types::RenameSource,
  SessionRenameReceipt, SessionTitleResolution, TitlePrecedenceLevel (POS: Domain contracts.)
- agent.context_management.session_metadata_rename.session_metadata_rename_engine::SessionMetadataRecord,
  SessionMetadataRenameEngine (POS: Atomic storage and mutation engine.)
- agent.context_management.session_metadata_rename.session_metadata_rename_suite::HapiRenameMetadataNameSuite
  (POS: High-level orchestration facade.)

[OUTPUT]
- Re-exports: HapiRenameMetadataNameSuite, RenameSource, SessionMetadataRecord,
  SessionMetadataRenameEngine, SessionRenameReceipt, SessionTitleResolution,
  TitlePrecedenceLevel, normalize_session_display_title, resolve_session_display_title

[POS]
Package entry point for session display title metadata-name precedence workflows.
"""

from __future__ import annotations

from .metadata_name_resolver import (
    normalize_session_display_title,
    resolve_session_display_title,
)
from .metadata_rename_types import (
    RenameSource,
    SessionRenameReceipt,
    SessionTitleResolution,
    TitlePrecedenceLevel,
)
from .session_metadata_rename_engine import (
    SessionMetadataRecord,
    SessionMetadataRenameEngine,
)
from .session_metadata_rename_suite import HapiRenameMetadataNameSuite

__all__ = [
    "HapiRenameMetadataNameSuite",
    "RenameSource",
    "SessionMetadataRecord",
    "SessionMetadataRenameEngine",
    "SessionRenameReceipt",
    "SessionTitleResolution",
    "TitlePrecedenceLevel",
    "normalize_session_display_title",
    "resolve_session_display_title",
]
