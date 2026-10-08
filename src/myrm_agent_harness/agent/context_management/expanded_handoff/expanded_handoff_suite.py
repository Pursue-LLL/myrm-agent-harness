"""Comprehensive facade suite for 1,200-word expanded dialogue skeleton and searchable archive handoff.

[INPUT]
- HistoricalSessionTurn: Conversation turns recorded from origin session.
- ExpandedHandoffConfig: Configuration governing budget and retrieval thresholds.
- ExpandedSkeletonAnchorBuilder, SearchableOldSessionArchiveConduit: Underlying engines.

[OUTPUT]
- FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite: Primary facade for Item 310.
- ExpandedHandoffSuite: Convenient alias.

[POS]
Main entry point coordinating 1,200-word expanded anchors and dynamic historical search back.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .expanded_skeleton_anchor_builder import ExpandedSkeletonAnchorBuilder
from .handoff_types import (
    ArchiveSearchResult,
    ExpandedHandoffAnchor,
    ExpandedHandoffConfig,
    HistoricalSessionTurn,
)
from .searchable_old_session_archive_conduit import SearchableOldSessionArchiveConduit


class FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite:
    """Unified facade managing rich 1,200-word cross-session handoff anchors and on-demand searchback."""

    def __init__(self, config: ExpandedHandoffConfig | None = None) -> None:
        self._config = config or ExpandedHandoffConfig()
        self._builder = ExpandedSkeletonAnchorBuilder(self._config)
        self._conduit = SearchableOldSessionArchiveConduit(self._config)

    @property
    def config(self) -> ExpandedHandoffConfig:
        """The configuration in effect."""
        return self._config

    def create_handoff_anchor(
        self,
        origin_session_id: str,
        target_session_id: str,
        turns: Sequence[HistoricalSessionTurn],
        title: str = "",
    ) -> ExpandedHandoffAnchor:
        """Construct a 1,200-word expanded dialogue anchor and register origin turns for on-demand search."""
        self._conduit.register_archive(session_id=origin_session_id, turns=turns)
        return self._builder.build_anchor(
            origin_session_id=origin_session_id,
            target_session_id=target_session_id,
            turns=turns,
            title=title,
        )

    def search_origin_archive(
        self,
        session_id: str,
        query: str,
        top_k: int | None = None,
    ) -> Sequence[ArchiveSearchResult]:
        """Perform on-demand targeted search against an origin session's immutable archive."""
        return self._conduit.search_archive(session_id=session_id, query=query, top_k=top_k)

    def get_search_tool_spec(self) -> Mapping[str, object]:
        """Return the function tool definition for the origin archive search conduit."""
        return self._conduit.generate_tool_definition()

    def render_handoff_context_injection(self, anchor: ExpandedHandoffAnchor) -> str:
        """Render a full injection prompt block for the target session containing skeleton and search conduit."""
        blocks: list[str] = [
            anchor.expanded_skeleton_text,
        ]

        if self._config.include_search_conduit_instructions:
            conduit_banner = (
                "\n---\n"
                "### 🔍 [A Way Back: Origin Session Search Conduit]\n"
                f"You have inherited this context from prior session `{anchor.origin_session_id}`.\n"
                "If you need exact unsummarized details (full stack traces, specific CLI flags, raw payloads), "
                f"call tool `search_origin_session_archive` with `session_id='{anchor.origin_session_id}'` "
                "to retrieve the exact original historical transcript."
            )
            blocks.append(conduit_banner)

        return "\n".join(blocks).strip()


ExpandedHandoffSuite = FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite
