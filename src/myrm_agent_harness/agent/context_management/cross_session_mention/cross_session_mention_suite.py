# [INPUT]: CrossSessionConfig, MentionInjectionResult, SessionMentionTag, SessionRecord, SessionSnapshot, SessionMentionParser, SessionSnapshotExtractor
# [OUTPUT]: CrossSessionMentionReferenceAndSnapshotInjectionSuite
# [POS]: agent/context_management/cross_session_mention/cross_session_mention_suite.py

"""End-to-end facade orchestrating cross-session @ mention references and read-only snapshot injection.

[INPUT]
- CrossSessionConfig: Configuration parameters and capacity limits.
- SessionRecord: Historical session entities.
- SessionMentionParser: Tag detector and identifier resolution engine.
- SessionSnapshotExtractor: Safe, read-only snapshot extractor.

[OUTPUT]
- CrossSessionMentionReferenceAndSnapshotInjectionSuite: Unified facade providing mention injection and fuzzy search.

[POS]
Main entry point and orchestrator for cross-session referencing in context management.
"""

from __future__ import annotations

from typing import Sequence

from .cross_session_types import (
    CrossSessionConfig,
    MentionInjectionResult,
    SessionMentionTag,
    SessionRecord,
    SessionSnapshot,
)
from .session_mention_parser import SessionMentionParser
from .session_snapshot_extractor import SessionSnapshotExtractor


class CrossSessionMentionReferenceAndSnapshotInjectionSuite:
    """Orchestrates in-composer mention detection, session fuzzy lookups, and snapshot envelope assembly."""

    def __init__(
        self,
        config: CrossSessionConfig | None = None,
        parser: SessionMentionParser | None = None,
        extractor: SessionSnapshotExtractor | None = None,
    ) -> None:
        self._config = config or CrossSessionConfig()
        self._parser = parser or SessionMentionParser(self._config)
        self._extractor = extractor or SessionSnapshotExtractor(self._config)

    @property
    def config(self) -> CrossSessionConfig:
        return self._config

    def parse_tags(self, text: str) -> Sequence[SessionMentionTag]:
        """Exposes raw tag parsing from prompt text."""
        return self._parser.parse_mentions(text)

    def search_sessions(
        self,
        query: str,
        available_sessions: Sequence[SessionRecord],
        limit: int = 5,
    ) -> Sequence[SessionRecord]:
        """Performs fuzzy and prefix scoring over historical sessions for composer dropdowns."""
        if not available_sessions:
            return []

        clean_query = query.strip().lower()
        if not clean_query:
            # Return most recent sessions up to limit
            sorted_recent = sorted(
                available_sessions, key=lambda s: s.created_at, reverse=True
            )
            return sorted_recent[:limit]

        scored: list[tuple[int, float, SessionRecord]] = []
        for sess in available_sessions:
            title_lower = sess.title.lower()
            id_lower = sess.session_id.lower()
            score = 0

            if clean_query == title_lower:
                score += 100
            elif title_lower.startswith(clean_query):
                score += 80
            elif clean_query in title_lower:
                score += 50

            if clean_query == id_lower:
                score += 90
            elif id_lower.startswith(clean_query):
                score += 70
            elif clean_query in id_lower:
                score += 40

            if sess.compacted_summary and clean_query in sess.compacted_summary.lower():
                score += 20

            if score > 0:
                scored.append((score, sess.created_at, sess))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:limit]]

    def inject_mentions(
        self,
        user_prompt: str,
        available_sessions: Sequence[SessionRecord],
    ) -> MentionInjectionResult:
        """Parses @Session mentions, extracts immutable snapshots, and constructs enriched prompt."""
        if not user_prompt:
            return MentionInjectionResult(
                original_user_prompt="",
                expanded_prompt="",
                referenced_snapshots=(),
                proof_badges=(),
                total_injected_tokens=0,
            )

        # 1. Parse and resolve mention tags
        raw_tags = self._parser.parse_mentions(user_prompt)
        resolved_tags = self._parser.resolve_mentions(raw_tags, available_sessions)

        # 2. Filter unique resolved session IDs respecting maximum session quota
        seen_ids: set[str] = set()
        resolved_session_ids: list[str] = []
        for tag in resolved_tags:
            if tag.is_resolved and tag.matched_session_id:
                sid = tag.matched_session_id
                if sid not in seen_ids:
                    seen_ids.add(sid)
                    resolved_session_ids.append(sid)
                    if len(resolved_session_ids) >= self._config.max_referenced_sessions:
                        break

        if not resolved_session_ids:
            return MentionInjectionResult(
                original_user_prompt=user_prompt,
                expanded_prompt=user_prompt,
                referenced_snapshots=(),
                proof_badges=(),
                total_injected_tokens=0,
            )

        # 3. Extract snapshots and collect badges
        session_map = {s.session_id: s for s in available_sessions}
        snapshots: list[SessionSnapshot] = []
        badges: list[str] = []
        for sid in resolved_session_ids:
            record = session_map.get(sid)
            if record is not None:
                snap = self._extractor.extract_snapshot(record)
                snapshots.append(snap)
                badges.append(snap.reference_badge)

        # 4. Construct read-only envelope
        envelope_blocks: list[str] = [
            "\n\n[REFERENCED HISTORICAL SESSION SNAPSHOTS (READ-ONLY)]",
            "The following context is mounted as immutable reference material from prior sessions:",
        ]

        for snap in snapshots:
            block = [
                f"\n### Referenced Session: \"{snap.title}\" (ID: {snap.session_id})",
                snap.summary_content,
            ]
            if snap.key_artifacts:
                block.append("Key Artifacts:\n" + "\n".join(f"- {a}" for a in snap.key_artifacts))
            block.append("---")
            envelope_blocks.append("\n".join(block))

        envelope_text = "\n".join(envelope_blocks)
        expanded_prompt = f"{user_prompt}{envelope_text}"

        total_tokens = sum(s.token_estimate for s in snapshots)
        envelope_overhead_tokens = max(1, (len(envelope_text) + 3) // 4)
        total_injected_tokens = max(total_tokens, envelope_overhead_tokens)

        return MentionInjectionResult(
            original_user_prompt=user_prompt,
            expanded_prompt=expanded_prompt,
            referenced_snapshots=tuple(snapshots),
            proof_badges=tuple(badges),
            total_injected_tokens=total_injected_tokens,
        )
