# [INPUT]: CrossSessionConfig, SessionMentionTag, SessionRecord
# [OUTPUT]: SessionMentionParser
# [POS]: agent/context_management/cross_session_mention/session_mention_parser.py

"""Parser and identifier resolver for @Session mentions within user prompt text.

[INPUT]
- CrossSessionConfig: Configuration governing mention prefix.
- SessionMentionTag: Domain dataclass representing parsed tag positions.
- SessionRecord: Historical session candidates used to resolve references.

[OUTPUT]
- SessionMentionParser: Stateless engine to detect and match @Session tags against session records.

[POS]
Lexical and tag matching layer in cross-session context referencing.
"""

from __future__ import annotations

import re
from typing import Sequence

from .cross_session_types import CrossSessionConfig, SessionMentionTag, SessionRecord


class SessionMentionParser:
    """Detects and resolves @Session:<id_or_title> mentions in input text."""

    def __init__(self, config: CrossSessionConfig | None = None) -> None:
        self._config = config or CrossSessionConfig()
        # Regex captures:
        # 1. Quoted with double quotes: @Session:"some session title"
        # 2. Quoted with single quotes: @Session:'some session title'
        # 3. Unquoted token: @Session:session_id_or_keyword (up to whitespace/punctuation)
        escaped_prefix = re.escape(self._config.mention_prefix)
        self._pattern = re.compile(
            rf"{escaped_prefix}(?:\"([^\"]+)\"|'([^']+)'|([^\s,;，。！？\n\r]+))",
            re.IGNORECASE,
        )

    def parse_mentions(self, text: str) -> Sequence[SessionMentionTag]:
        """Scans input string and returns all detected SessionMentionTag references."""
        if not text:
            return []

        tags: list[SessionMentionTag] = []
        for match in self._pattern.finditer(text):
            raw_match = match.group(0)
            identifier = match.group(1) or match.group(2) or match.group(3) or ""
            identifier = identifier.strip()
            if not identifier:
                continue

            tags.append(
                SessionMentionTag(
                    raw_match=raw_match,
                    identifier=identifier,
                    start_pos=match.start(),
                    end_pos=match.end(),
                    matched_session_id=None,
                    is_resolved=False,
                )
            )
        return tags

    def resolve_mentions(
        self,
        tags: Sequence[SessionMentionTag],
        available_sessions: Sequence[SessionRecord],
    ) -> Sequence[SessionMentionTag]:
        """Matches extracted tags against available session records by ID or title."""
        if not tags or not available_sessions:
            return tags

        # Precompute lookup indexes for exact ID and normalized title
        by_id: dict[str, SessionRecord] = {s.session_id: s for s in available_sessions}
        by_title_lower: dict[str, SessionRecord] = {
            s.title.strip().lower(): s for s in available_sessions
        }

        resolved: list[SessionMentionTag] = []
        for tag in tags:
            ident_clean = tag.identifier.strip()
            ident_lower = ident_clean.lower()

            target_session: SessionRecord | None = None
            # 1. Exact match on session_id
            if ident_clean in by_id:
                target_session = by_id[ident_clean]
            # 2. Exact match on title (case-insensitive)
            elif ident_lower in by_title_lower:
                target_session = by_title_lower[ident_lower]
            else:
                # 3. Substring / prefix match on title or ID
                for sess in available_sessions:
                    title_norm = sess.title.lower()
                    id_norm = sess.session_id.lower()
                    if ident_lower in title_norm or ident_lower in id_norm:
                        target_session = sess
                        break

            if target_session is not None:
                resolved.append(
                    SessionMentionTag(
                        raw_match=tag.raw_match,
                        identifier=tag.identifier,
                        start_pos=tag.start_pos,
                        end_pos=tag.end_pos,
                        matched_session_id=target_session.session_id,
                        is_resolved=True,
                    )
                )
            else:
                resolved.append(tag)

        return resolved
