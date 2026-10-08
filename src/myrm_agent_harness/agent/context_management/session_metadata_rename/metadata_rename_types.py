"""Domain contracts for session display rename and metadata-name precedence resolution.

[INPUT]
- None (Self-contained strongly typed domain definitions).

[OUTPUT]
- RenameSource: Source category initiating a session rename operation.
- TitlePrecedenceLevel: Priority tier from which a display title is resolved.
- SessionRenameReceipt: Strongly typed audit receipt for session rename mutations.
- SessionTitleResolution: Structured outcome describing resolved display title and its origin.

[POS]
Domain contracts for session display title precedence and metadata.name consistency.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time


class RenameSource(str, Enum):
    """Source entity initiating the session title mutation."""

    USER_EXPLICIT = "user_explicit"
    OPERATOR = "operator"
    AGENT_TOOL = "agent_tool"
    AUTO_SUMMARY = "auto_summary"


class TitlePrecedenceLevel(str, Enum):
    """Precedence hierarchy for resolving the authoritative session display title."""

    METADATA_NAME = "metadata_name"
    METADATA_TITLE = "metadata_title"
    TOPLEVEL_NAME = "toplevel_name"
    FALLBACK_SUMMARY = "fallback_summary"
    DEFAULT_FALLBACK = "default_fallback"


@dataclass(frozen=True)
class SessionRenameReceipt:
    """Audit receipt returned after applying a session display rename."""

    session_id: str
    normalized_name: str
    previous_name: str | None
    changed: bool
    source: RenameSource
    timestamp_utc: float
    success: bool
    message: str


@dataclass(frozen=True)
class SessionTitleResolution:
    """Result of resolving session display title according to strict precedence rules."""

    effective_title: str
    precedence_level: TitlePrecedenceLevel
    is_explicit_rename: bool
    raw_source_field: str
