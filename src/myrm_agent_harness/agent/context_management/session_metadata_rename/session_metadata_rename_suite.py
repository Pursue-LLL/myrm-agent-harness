"""End-to-end orchestration facade for session metadata display renaming and precedence arbitration.

[INPUT]
- agent.context_management.session_metadata_rename.metadata_name_resolver::normalize_session_display_title,
  resolve_session_display_title (POS: Functional normalizer and precedence resolver.)
- agent.context_management.session_metadata_rename.metadata_rename_types::RenameSource,
  SessionRenameReceipt, SessionTitleResolution, TitlePrecedenceLevel (POS: Domain models.)
- agent.context_management.session_metadata_rename.session_metadata_rename_engine::SessionMetadataRecord,
  SessionMetadataRenameEngine (POS: Atomic storage and mutation engine.)

[OUTPUT]
- HapiRenameMetadataNameSuite: Unified facade delivering explicit metadata.name updates,
  collaboration guardrails, and deterministic title precedence resolution.

[POS]
High-level suite unifying session renaming and display title precedence.
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


class HapiRenameMetadataNameSuite:
    """Unified facade managing session display rename via metadata.name and precedence resolution."""

    def __init__(self, engine: SessionMetadataRenameEngine | None = None) -> None:
        self._engine = engine or SessionMetadataRenameEngine()

    @property
    def engine(self) -> SessionMetadataRenameEngine:
        """Access underlying metadata rename engine."""
        return self._engine

    def register_session(
        self,
        session_id: str,
        initial_metadata: dict[str, str] | None = None,
        toplevel_name: str | None = None,
    ) -> SessionMetadataRecord:
        """Register a session with initial metadata and optional top-level title."""
        return self._engine.register_session(
            session_id=session_id,
            initial_metadata=initial_metadata,
            toplevel_name=toplevel_name,
        )

    def rename_session(
        self,
        session_id: str,
        new_title: str | None,
        source: RenameSource = RenameSource.USER_EXPLICIT,
        allow_subagent_rename: bool = True,
        is_subagent: bool = False,
    ) -> SessionRenameReceipt:
        """Apply an explicit rename operation targeting metadata.name."""
        return self._engine.apply_rename(
            session_id=session_id,
            new_title=new_title,
            source=source,
            allow_subagent_rename=allow_subagent_rename,
            is_subagent=is_subagent,
        )

    def resolve_display_title(
        self,
        session_id: str,
        fallback_summary: str | None = None,
        default_fallback: str = "Untitled Session",
    ) -> SessionTitleResolution:
        """Resolve authoritative display title following strict precedence rules."""
        return self._engine.resolve_title(
            session_id=session_id,
            fallback_summary=fallback_summary,
            default_fallback=default_fallback,
        )

    def normalize_title(self, title: str | None, max_length: int = 255) -> str | None:
        """Helper to sanitize and normalize title strings."""
        return normalize_session_display_title(title=title, max_length=max_length)

    def resolve_metadata_direct(
        self,
        metadata: dict[str, str],
        toplevel_name: str | None = None,
        fallback_summary: str | None = None,
        default_fallback: str = "Untitled Session",
    ) -> SessionTitleResolution:
        """Pure-functional direct resolution without requiring registered session records."""
        return resolve_session_display_title(
            metadata=metadata,
            toplevel_name=toplevel_name,
            fallback_summary=fallback_summary,
            default_fallback=default_fallback,
        )
