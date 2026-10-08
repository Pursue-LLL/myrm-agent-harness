"""Precedence resolver and title normalizer for session display naming.

[INPUT]
- agent.context_management.session_metadata_rename.metadata_rename_types::SessionTitleResolution,
  TitlePrecedenceLevel (POS: Strongly typed contracts for resolved title and precedence tiers.)

[OUTPUT]
- normalize_session_display_title: Sanitizes whitespace, strips control characters, and enforces length bounds.
- resolve_session_display_title: Resolves authoritative display title following strict precedence hierarchy.

[POS]
Pure functional resolver for session title normalization and precedence arbitration.
"""

from __future__ import annotations

import re

from .metadata_rename_types import (
    SessionTitleResolution,
    TitlePrecedenceLevel,
)

_WHITESPACE_COLLAPSE_PATTERN = re.compile(r"\s+")


def normalize_session_display_title(title: str | None, max_length: int = 255) -> str | None:
    """Sanitize and normalize session title text.

    Collapses consecutive whitespace, strips leading/trailing spaces,
    and bounds the maximum length. Returns None if the input is empty or blank.

    Args:
        title: Candidate title string or None.
        max_length: Maximum allowed character length.

    Returns:
        Clean normalized title string, or None if empty.
    """
    if title is None:
        return None

    stripped = title.strip()
    if not stripped:
        return None

    collapsed = _WHITESPACE_COLLAPSE_PATTERN.sub(" ", stripped)
    if len(collapsed) > max_length:
        collapsed = collapsed[:max_length].rstrip()

    return collapsed if collapsed else None


def resolve_session_display_title(
    metadata: dict[str, str],
    toplevel_name: str | None = None,
    fallback_summary: str | None = None,
    default_fallback: str = "Untitled Session",
) -> SessionTitleResolution:
    """Resolve session display title strictly following unified precedence rules.

    Precedence order:
    1. metadata['name'] (Explicit agent/user rename - single source of truth)
    2. metadata['title'] (Legacy or auxiliary metadata alias)
    3. toplevel_name (Top-level container/session attribute)
    4. fallback_summary (Auto-generated prompt/first-turn summary)
    5. default_fallback (Deterministic safe default)

    Args:
        metadata: Session key-value metadata mapping.
        toplevel_name: Optional top-level session entity name.
        fallback_summary: Optional auto-generated conversation summary.
        default_fallback: Fallback label when no title candidates exist.

    Returns:
        Structured SessionTitleResolution containing effective title and its precedence tier.
    """
    # 1. Authoritative explicit name in metadata.name
    meta_name = normalize_session_display_title(metadata.get("name"))
    if meta_name:
        return SessionTitleResolution(
            effective_title=meta_name,
            precedence_level=TitlePrecedenceLevel.METADATA_NAME,
            is_explicit_rename=True,
            raw_source_field="metadata.name",
        )

    # 2. Legacy alias in metadata.title
    meta_title = normalize_session_display_title(metadata.get("title"))
    if meta_title:
        return SessionTitleResolution(
            effective_title=meta_title,
            precedence_level=TitlePrecedenceLevel.METADATA_TITLE,
            is_explicit_rename=True,
            raw_source_field="metadata.title",
        )

    # 3. Top-level session attribute
    norm_top = normalize_session_display_title(toplevel_name)
    if norm_top:
        return SessionTitleResolution(
            effective_title=norm_top,
            precedence_level=TitlePrecedenceLevel.TOPLEVEL_NAME,
            is_explicit_rename=False,
            raw_source_field="session.name",
        )

    # 4. Auto-generated fallback summary
    norm_summary = normalize_session_display_title(fallback_summary)
    if norm_summary:
        return SessionTitleResolution(
            effective_title=norm_summary,
            precedence_level=TitlePrecedenceLevel.FALLBACK_SUMMARY,
            is_explicit_rename=False,
            raw_source_field="fallback_summary",
        )

    # 5. Default safe fallback
    return SessionTitleResolution(
        effective_title=default_fallback,
        precedence_level=TitlePrecedenceLevel.DEFAULT_FALLBACK,
        is_explicit_rename=False,
        raw_source_field="default",
    )
