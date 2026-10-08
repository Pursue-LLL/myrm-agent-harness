# [INPUT]: metadata_name_resolver.py, metadata_rename_types.py
# [OUTPUT]: SessionMetadataRecord, SessionMetadataRenameEngine
# [POS]: agent/context_management/session_metadata_rename/session_metadata_rename_engine.py

"""Core mutation and storage engine for session display renaming via metadata.name.

[INPUT]
- agent.context_management.session_metadata_rename.metadata_name_resolver::normalize_session_display_title,
  resolve_session_display_title (POS: Functional normalizer and precedence resolver.)
- agent.context_management.session_metadata_rename.metadata_rename_types::RenameSource,
  SessionRenameReceipt, SessionTitleResolution (POS: Strongly typed domain contracts.)

[OUTPUT]
- SessionMetadataRecord: Active entity tracking session metadata, toplevel attributes, and rename audit history.
- SessionMetadataRenameEngine: Engine managing atomic metadata mutations, idempotency, and subagent permissions.

[POS]
Mutation engine ensuring metadata.name is the authoritative single source of truth for session display naming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time

from .metadata_name_resolver import (
    normalize_session_display_title,
    resolve_session_display_title,
)
from .metadata_rename_types import (
    RenameSource,
    SessionRenameReceipt,
    SessionTitleResolution,
)


@dataclass
class SessionMetadataRecord:
    """Internal session entity preserving metadata and naming attributes."""

    session_id: str
    metadata: dict[str, str] = field(default_factory=dict)
    toplevel_name: str | None = None
    created_at_utc: float = field(default_factory=time.time)
    last_renamed_at_utc: float | None = None
    rename_count: int = 0


class SessionMetadataRenameEngine:
    """Coordinates atomic session renaming to metadata.name and enforces precedence rules."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionMetadataRecord] = {}

    def register_session(
        self,
        session_id: str,
        initial_metadata: dict[str, str] | None = None,
        toplevel_name: str | None = None,
    ) -> SessionMetadataRecord:
        """Register or retrieve a session metadata record.

        Args:
            session_id: Unique session identifier.
            initial_metadata: Initial key-value metadata attributes.
            toplevel_name: Optional top-level container name.

        Returns:
            The registered SessionMetadataRecord.
        """
        if session_id in self._sessions:
            rec = self._sessions[session_id]
            if initial_metadata:
                rec.metadata.update(initial_metadata)
            if toplevel_name is not None:
                rec.toplevel_name = toplevel_name
            return rec

        record = SessionMetadataRecord(
            session_id=session_id,
            metadata=dict(initial_metadata or {}),
            toplevel_name=toplevel_name,
            created_at_utc=time.time(),
        )
        self._sessions[session_id] = record
        return record

    def get_session(self, session_id: str) -> SessionMetadataRecord:
        """Retrieve a session by its identifier.

        Args:
            session_id: The session identifier.

        Returns:
            SessionMetadataRecord instance.

        Raises:
            KeyError: If session_id is not found.
        """
        if session_id not in self._sessions:
            msg = f"Session '{session_id}' not found."
            raise KeyError(msg)
        return self._sessions[session_id]

    def has_session(self, session_id: str) -> bool:
        """Check whether a session exists."""
        return session_id in self._sessions

    def apply_rename(
        self,
        session_id: str,
        new_title: str | None,
        source: RenameSource = RenameSource.USER_EXPLICIT,
        allow_subagent_rename: bool = True,
        is_subagent: bool = False,
    ) -> SessionRenameReceipt:
        """Apply an explicit rename operation targeting metadata.name.

        Args:
            session_id: The session identifier.
            new_title: The candidate new title.
            source: Source of the rename directive.
            allow_subagent_rename: Policy flag whether subagents can rename parent sessions.
            is_subagent: Whether the caller is an untrusted child subagent.

        Returns:
            SessionRenameReceipt describing operation outcome.
        """
        now = time.time()
        record = self.register_session(session_id)
        prev_name = record.metadata.get("name")

        # 1. Reject subagent renaming when collaboration policy disallows it
        if is_subagent and not allow_subagent_rename:
            return SessionRenameReceipt(
                session_id=session_id,
                normalized_name=prev_name or "",
                previous_name=prev_name,
                changed=False,
                source=source,
                timestamp_utc=now,
                success=False,
                message="Subagent renaming rejected by collaboration policy.",
            )

        # 2. Normalize candidate title
        normalized = normalize_session_display_title(new_title)
        if not normalized:
            return SessionRenameReceipt(
                session_id=session_id,
                normalized_name="",
                previous_name=prev_name,
                changed=False,
                source=source,
                timestamp_utc=now,
                success=False,
                message="Rename rejected: title is empty or blank after normalization.",
            )

        # 3. Idempotent check: if already identical, skip redundant mutation
        if prev_name and prev_name.strip() == normalized:
            return SessionRenameReceipt(
                session_id=session_id,
                normalized_name=normalized,
                previous_name=prev_name,
                changed=False,
                source=source,
                timestamp_utc=now,
                success=True,
                message="Title already identical (idempotent no-op).",
            )

        # 4. Atomic write to metadata.name (authoritative SSOT)
        record.metadata["name"] = normalized
        record.last_renamed_at_utc = now
        record.rename_count += 1

        return SessionRenameReceipt(
            session_id=session_id,
            normalized_name=normalized,
            previous_name=prev_name,
            changed=True,
            source=source,
            timestamp_utc=now,
            success=True,
            message="Session display title successfully updated in metadata.name.",
        )

    def resolve_title(
        self,
        session_id: str,
        fallback_summary: str | None = None,
        default_fallback: str = "Untitled Session",
    ) -> SessionTitleResolution:
        """Resolve authoritative display title for a registered session.

        Args:
            session_id: The session identifier.
            fallback_summary: Optional auto-generated conversation summary.
            default_fallback: Default string when no candidate exists.

        Returns:
            SessionTitleResolution detailing effective title and origin tier.
        """
        if session_id not in self._sessions:
            return SessionTitleResolution(
                effective_title=default_fallback,
                precedence_level=resolve_session_display_title(
                    metadata={},
                    fallback_summary=fallback_summary,
                    default_fallback=default_fallback,
                ).precedence_level,
                is_explicit_rename=False,
                raw_source_field="unregistered",
            )

        record = self._sessions[session_id]
        return resolve_session_display_title(
            metadata=record.metadata,
            toplevel_name=record.toplevel_name,
            fallback_summary=fallback_summary,
            default_fallback=default_fallback,
        )
