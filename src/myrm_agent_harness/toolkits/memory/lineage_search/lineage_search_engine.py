"""Full-stack session retrieval engine with FTS5 lexical matching,.

[INPUT]
- toolkits.memory.lineage_search.lineage_deduplicator::LineageDeduplicator (POS: Collapses multi-generation
  compacted or branched session continuations.)
- toolkits.memory.lineage_search.models::ConversationMessage, HydratedSessionHit, LineageSearchOptions,
  LineageSearchStats, RawSearchHit, SessionMeta, SessionSourceKind (POS: Types and models for lineage search.)
- toolkits.memory.lineage_search.source_demoter::SourceDemoterAndFilter (POS: Implements source-aware
  filtering and demotion policies inspired by Hermes Agent PR #19434.)
- toolkits.memory.lineage_search.window_hydrator::AdaptiveWindowHydrator (POS: Hydrates surviving search hits
  with two-tier adaptive detail:.)

[OUTPUT]
- LineageSearchEngine: Full-stack session retrieval engine with FTS5 lexical matching,.

[POS]
Full-stack session retrieval engine with FTS5 lexical matching,.
"""

# [POS]: myrm_agent_harness/toolkits/memory/lineage_search/lineage_search_engine.py
# [INPUT]: SQLite database path or in-memory, session metadata, conversation messages
# [OUTPUT]: LineageSearchEngine orchestrating FTS5 search, source demotion, lineage dedup, and hydration

import datetime
import sqlite3
from collections import defaultdict
from pathlib import Path

from myrm_agent_harness.toolkits.memory.lineage_search.lineage_deduplicator import LineageDeduplicator
from myrm_agent_harness.toolkits.memory.lineage_search.models import (
    ConversationMessage,
    HydratedSessionHit,
    LineageSearchOptions,
    LineageSearchStats,
    RawSearchHit,
    SessionMeta,
    SessionSourceKind,
)
from myrm_agent_harness.toolkits.memory.lineage_search.source_demoter import SourceDemoterAndFilter
from myrm_agent_harness.toolkits.memory.lineage_search.window_hydrator import AdaptiveWindowHydrator


class LineageSearchEngine:
    """Full-stack session retrieval engine with FTS5 lexical matching,

    lineage root deduplication, automation source demotion (PR #19434),
    and adaptive token-conserving window hydration.
    """

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        anchor_window: int = 5,
        bookend_count: int = 3,
    ) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._demoter = SourceDemoterAndFilter()
        self._deduplicator = LineageDeduplicator()
        self._hydrator = AdaptiveWindowHydrator(anchor_window=anchor_window, bookend_count=bookend_count)
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize relational session catalog and FTS5 full-text virtual table."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT,
                    source TEXT,
                    lineage_root_id TEXT,
                    parent_session_id TEXT,
                    model TEXT,
                    started_at TEXT
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    created_at TEXT,
                    sequence_num INTEGER
                );
                """
            )
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    message_id UNINDEXED,
                    session_id UNINDEXED,
                    role UNINDEXED,
                    content,
                    tokenize = 'unicode61'
                );
                """
            )

    def add_session(self, meta: SessionMeta) -> None:
        """Register or update session metadata."""
        started_at = meta.started_at or datetime.datetime.now(datetime.UTC).isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO sessions(session_id, title, source, lineage_root_id, parent_session_id, model, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    meta.session_id,
                    meta.title,
                    meta.source.value,
                    meta.lineage_root_id,
                    meta.parent_session_id,
                    meta.model,
                    started_at,
                ),
            )

    def add_message(self, msg: ConversationMessage) -> None:
        """Add message to storage and index into FTS5 virtual table."""
        created_at = msg.created_at or datetime.datetime.now(datetime.UTC).isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO messages(message_id, session_id, role, content, created_at, sequence_num)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (msg.message_id, msg.session_id, msg.role, msg.content, created_at, msg.sequence_num),
            )
            # Maintain FTS table
            self._conn.execute(
                "DELETE FROM messages_fts WHERE message_id = ?;",
                (msg.message_id,),
            )
            self._conn.execute(
                """
                INSERT INTO messages_fts(message_id, session_id, role, content)
                VALUES (?, ?, ?, ?);
                """,
                (msg.message_id, msg.session_id, msg.role, msg.content),
            )

    def get_session(self, session_id: str) -> SessionMeta | None:
        """Retrieve session metadata by session ID."""
        cur = self._conn.execute(
            "SELECT session_id, title, source, lineage_root_id, parent_session_id, model, started_at FROM sessions WHERE session_id = ? LIMIT 1;",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return SessionMeta(
            session_id=str(row["session_id"]),
            title=str(row["title"]),
            source=SessionSourceKind(str(row["source"])),
            lineage_root_id=str(row["lineage_root_id"]),
            parent_session_id=str(row["parent_session_id"]),
            model=str(row["model"]),
            started_at=str(row["started_at"]),
        )

    def get_messages(self, session_id: str) -> list[ConversationMessage]:
        """Fetch all ordered messages for a session."""
        cur = self._conn.execute(
            "SELECT message_id, session_id, role, content, created_at, sequence_num FROM messages WHERE session_id = ? ORDER BY sequence_num ASC, created_at ASC;",
            (session_id,),
        )
        rows = cur.fetchall()
        return [
            ConversationMessage(
                message_id=str(r["message_id"]),
                session_id=str(r["session_id"]),
                role=str(r["role"]),
                content=str(r["content"]),
                created_at=str(r["created_at"]),
                sequence_num=int(r["sequence_num"]),
            )
            for r in rows
        ]

    def search(self, options: LineageSearchOptions) -> list[HydratedSessionHit]:
        """Execute discovery search with source demotion, lineage dedup, and adaptive hydration."""
        cleaned_query = "".join(c for c in options.query if c.isalnum() or c in (" ", "\u4e00-\u9fff")).strip()
        if not cleaned_query:
            return []

        # 1. Over-scan FTS matches
        cur = self._conn.execute(
            """
            SELECT message_id, session_id, role, content, bm25(messages_fts) AS bm25_score
            FROM messages_fts
            WHERE messages_fts MATCH ?
            ORDER BY bm25_score ASC
            LIMIT ?;
            """,
            (f'"{cleaned_query}"', options.max_scan_limit),
        )
        rows = cur.fetchall()
        if not rows:
            return []

        # 2. Gather session metadata and messages
        session_ids = {str(r["session_id"]) for r in rows}
        session_metas: dict[str, SessionMeta] = {}
        for sid in session_ids:
            s_meta = self.get_session(sid)
            if s_meta:
                session_metas[sid] = s_meta

        raw_hits: list[RawSearchHit] = []
        for r in rows:
            sid = str(r["session_id"])
            mid = str(r["message_id"])
            role = str(r["role"])
            content = str(r["content"])
            raw_bm25 = float(r["bm25_score"])
            # Invert BM25 score to positive score
            score = round(abs(raw_bm25) + 1.0, 4)
            source_kind = session_metas[sid].source if sid in session_metas else SessionSourceKind.INTERACTIVE
            raw_hits.append(
                RawSearchHit(
                    session_id=sid,
                    message_id=mid,
                    role=role,
                    content_snippet=content[:150],
                    score=score,
                    source=source_kind,
                )
            )

        # 3. Source Filtering & Demotion (PR #19434)
        filtered_hits = self._demoter.filter_and_demote(
            hits=raw_hits,
            session_metas=session_metas,
            include_hidden=options.include_hidden,
        )

        # 4. Lineage Root Deduplication
        deduped_candidates = self._deduplicator.deduplicate(
            hits=filtered_hits,
            session_metas=session_metas,
            limit=options.limit,
        )

        # 5. Load full conversation messages for surviving candidate sessions
        message_store: dict[str, list[ConversationMessage]] = defaultdict(list)
        for hit, _ in deduped_candidates:
            if hit.session_id not in message_store:
                message_store[hit.session_id] = self.get_messages(hit.session_id)

        # 6. Adaptive Window Hydration (Top 1 full, Top 2-N compact)
        return self._hydrator.hydrate(
            deduped_candidates=deduped_candidates,
            session_metas=session_metas,
            message_store=message_store,
        )

    def get_stats(self) -> LineageSearchStats:
        """Return operational telemetry."""
        cur_s = self._conn.execute("SELECT count(*), source FROM sessions GROUP BY source;")
        rows_s = cur_s.fetchall()
        total_s = 0
        hidden_count = 0
        demoted_count = 0
        for r in rows_s:
            cnt = int(r[0])
            src = SessionSourceKind(str(r[1]))
            total_s += cnt
            if SourceDemoterAndFilter.is_hidden(src):
                hidden_count += cnt
            elif SourceDemoterAndFilter.is_demoted(src):
                demoted_count += cnt

        cur_m = self._conn.execute("SELECT count(*) FROM messages;")
        total_m = int(cur_m.fetchone()[0])

        return LineageSearchStats(
            total_sessions=total_s,
            total_messages=total_m,
            hidden_sources_count=hidden_count,
            demoted_sources_count=demoted_count,
        )

    def close(self) -> None:
        """Close SQLite database connection."""
        self._conn.close()
