"""Core engine for Agent Session History FTS5 Search Toolkit.

[INPUT]
- session_search_types: Domain query contracts, hit models, and search scope enums.

[OUTPUT]
- SessionHistoryFTS5SearchEngine: SQLite FTS5-backed full-text search and verbatim recall engine.

[POS]
Indexes dialogue turns into an in-process SQLite FTS5 virtual table,
enabling exact factual recall and verbatim output recovery across compressed history.
"""

from __future__ import annotations

import re
import sqlite3
import time

from myrm_agent_harness.agent.context_management.session_search.session_search_types import (
    SearchRoleFilter,
    SessionSearchHit,
    SessionSearchQuery,
    SessionSearchResult,
    SessionSearchScope,
)


class SessionHistoryFTS5SearchEngine:
    """In-process SQLite FTS5 full-text search engine for historical agent dialogue sessions."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Initializes raw message store and FTS5 virtual table schema."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_messages_verbatim (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    tool_name TEXT,
                    full_content TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS session_messages_fts USING fts5(
                    message_id UNINDEXED,
                    session_id,
                    turn_index UNINDEXED,
                    role,
                    tool_name,
                    content,
                    tokenize='porter unicode61'
                );
                """
            )

    @staticmethod
    def _tokenize_cjk_for_fts(text: str) -> str:
        """Inserts spaces around CJK characters to enable fine-grained character-level FTS5 indexing."""
        spaced = re.sub(r"([\u4e00-\u9fff\u3400-\u4dbf])", r" \1 ", text)
        return " ".join(spaced.split())

    def index_message(
        self,
        message_id: str,
        session_id: str,
        turn_index: int,
        role: str,
        content: str,
        tool_name: str | None = None,
    ) -> None:
        """Indexes a message turn into both verbatim storage and FTS5 full-text index."""
        now = time.time()
        tool_str = tool_name or ""
        fts_content = self._tokenize_cjk_for_fts(content)
        with self._conn:
            # 1. Insert or replace verbatim content
            self._conn.execute(
                """
                INSERT OR REPLACE INTO session_messages_verbatim
                (message_id, session_id, turn_index, role, tool_name, full_content, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (message_id, session_id, turn_index, role, tool_str, content, now),
            )
            # 2. Insert into FTS5 virtual table
            self._conn.execute(
                """
                INSERT INTO session_messages_fts
                (message_id, session_id, turn_index, role, tool_name, content)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (message_id, session_id, str(turn_index), role, tool_str, fts_content),
            )

    @classmethod
    def _sanitize_fts_query(cls, raw_query: str) -> str:
        """Sanitizes user search query into valid FTS5 MATCH syntax with CJK awareness."""
        cleaned = re.sub(r'[^\w\s\*\-"\']', " ", raw_query.strip())
        tokens = [t.strip() for t in cleaned.split() if t.strip()]
        if not tokens:
            return '""'

        processed_tokens: list[str] = []
        for t in tokens:
            if t.upper() in ("AND", "OR", "NOT"):
                processed_tokens.append(t.upper())
            elif any("\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf" for ch in t):
                # CJK token: space out into unigrams and quote as phrase query
                cjk_phrase = cls._tokenize_cjk_for_fts(t)
                processed_tokens.append(f'"{cjk_phrase}"')
            elif t.startswith('"') and t.endswith('"'):
                processed_tokens.append(t)
            elif not t.endswith("*"):
                processed_tokens.append(f"{t}*")
            else:
                processed_tokens.append(t)
        return " ".join(processed_tokens)

    def search_history(self, query_spec: SessionSearchQuery) -> SessionSearchResult:
        """Executes full-text FTS5 search with filtering and verbatim output recovery."""
        start_time = time.perf_counter()
        fts_query = self._sanitize_fts_query(query_spec.query)

        # Base query joining FTS5 and verbatim tables
        sql_parts: list[str] = [
            """
            SELECT
                f.message_id,
                f.session_id,
                CAST(f.turn_index AS INTEGER) AS turn_index,
                f.role,
                f.tool_name,
                snippet(session_messages_fts, 5, '<b>', '</b>', '...', 16) AS snippet,
                bm25(session_messages_fts) AS rank,
                v.full_content
            FROM session_messages_fts f
            JOIN session_messages_verbatim v ON f.message_id = v.message_id
            WHERE session_messages_fts MATCH ?
            """
        ]
        params: list[str | int] = [fts_query]

        # Scope filter
        if query_spec.scope == SessionSearchScope.CURRENT_SESSION:
            sql_parts.append("AND f.session_id = ?")
            params.append(query_spec.session_id)

        # Role filter
        if query_spec.role != SearchRoleFilter.ALL:
            sql_parts.append("AND f.role = ?")
            params.append(query_spec.role.value)

        # Turn range filters
        if query_spec.turn_min is not None:
            sql_parts.append("AND CAST(f.turn_index AS INTEGER) >= ?")
            params.append(query_spec.turn_min)
        if query_spec.turn_max is not None:
            sql_parts.append("AND CAST(f.turn_index AS INTEGER) <= ?")
            params.append(query_spec.turn_max)

        sql_parts.append("ORDER BY rank LIMIT ?;")
        params.append(max(1, query_spec.limit))

        query_str = "\n".join(sql_parts)

        hits: list[SessionSearchHit] = []
        try:
            cursor = self._conn.execute(query_str, tuple(params))
            for row in cursor.fetchall():
                m_id = str(row["message_id"])
                s_id = str(row["session_id"])
                t_idx = int(row["turn_index"])
                role = str(row["role"])
                tool_name = str(row["tool_name"]) if row["tool_name"] else None
                snippet = str(row["snippet"])
                rank = float(row["rank"])
                full_content = str(row["full_content"]) if query_spec.include_full_output else None

                tool_detail = f" ({tool_name})" if tool_name else ""
                citation = f"[来源: 第 {t_idx} 轮 {role}{tool_detail}]"

                hit = SessionSearchHit(
                    message_id=m_id,
                    session_id=s_id,
                    turn_index=t_idx,
                    role=role,
                    tool_name=tool_name,
                    snippet=snippet,
                    full_content=full_content,
                    relevance_score=round(abs(rank), 4),
                    citation_tag=citation,
                )
                hits.append(hit)
        except sqlite3.OperationalError:
            # Fallback when search query syntax cannot be matched
            pass

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return SessionSearchResult(
            query=query_spec.query,
            total_hits=len(hits),
            hits=hits,
            search_duration_ms=round(duration_ms, 2),
        )

    def fetch_verbatim_message(self, message_id: str) -> str | None:
        """Retrieves raw uncompressed content of a specific historical message."""
        cursor = self._conn.execute(
            "SELECT full_content FROM session_messages_verbatim WHERE message_id = ?;",
            (message_id,),
        )
        row = cursor.fetchone()
        return str(row["full_content"]) if row else None

    def close(self) -> None:
        """Closes SQLite database connection."""
        self._conn.close()
