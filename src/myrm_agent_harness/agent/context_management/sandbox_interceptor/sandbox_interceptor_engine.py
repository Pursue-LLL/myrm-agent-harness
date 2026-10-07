"""Core engine for Sandbox Tool Output Interception, Local SQLite FTS5 Search, and Lifecycle Hooks.

Saves 98%+ of LLM context tokens by physically intercepting massive tool outputs (Playwright dumps,
git logs, compiler traces), archiving them into local SQLite with FTS5 indexing, and providing
exact snippet retrieval via ctx_search alongside five-stage lifecycle hooks.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from myrm_agent_harness.agent.context_management.sandbox_interceptor.sandbox_interceptor_types import (
    ContextHookStage,
    InterceptedToolOutput,
    LifecycleHookRecord,
    SandboxInterceptorConfig,
    SearchResultSnippet,
    ToolOutputStub,
)


class SandboxOutputInterceptorEngine:
    """Engine intercepting bulky tool results and providing local FTS5 exact search."""

    def __init__(self, config: SandboxInterceptorConfig | None = None) -> None:
        self.config: SandboxInterceptorConfig = config or SandboxInterceptorConfig()
        self._db: sqlite3.Connection = sqlite3.connect(
            self.config.sqlite_db_path,
            check_same_thread=False,
        )
        self._fts_available: bool = False
        self._init_storage()

    def _init_storage(self) -> None:
        """Initialize relational storage and FTS5 full-text indexing tables."""
        cursor = self._db.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_outputs (
                content_id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                session_id TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                raw_size_bytes INTEGER NOT NULL,
                summary_digest TEXT NOT NULL,
                line_count INTEGER NOT NULL,
                intercepted_at REAL NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS lifecycle_hooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stage TEXT NOT NULL,
                session_id TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                timestamp REAL NOT NULL
            );
            """
        )
        try:
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS tool_outputs_fts USING fts5(
                    content_id UNINDEXED,
                    raw_text,
                    tokenize='unicode61'
                );
                """
            )
            self._fts_available = True
        except sqlite3.OperationalError:
            self._fts_available = False

        self._db.commit()

    def intercept_tool_output(
        self,
        tool_name: str,
        raw_output: str,
        session_id: str,
    ) -> tuple[str, ToolOutputStub | None]:
        """Intercept bulky tool output if exceeding threshold, otherwise return unmodified."""
        raw_bytes = len(raw_output.encode("utf-8"))
        if raw_bytes <= self.config.interception_threshold_bytes:
            return raw_output, None

        content_id = f"tool_out_{uuid.uuid4().hex[:12]}"
        lines = raw_output.splitlines()
        line_count = len(lines)

        first_preview = lines[0][:120] if lines else ""
        last_preview = lines[-1][:120] if len(lines) > 1 else ""
        summary_digest = f"{first_preview}... [Total {line_count} lines] ...{last_preview}".strip()

        cursor = self._db.cursor()
        cursor.execute(
            """
            INSERT INTO tool_outputs (
                content_id, tool_name, session_id, raw_text,
                raw_size_bytes, summary_digest, line_count, intercepted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                content_id,
                tool_name,
                session_id,
                raw_output,
                raw_bytes,
                summary_digest,
                line_count,
                time.time(),
            ),
        )

        if self._fts_available:
            cursor.execute(
                "INSERT INTO tool_outputs_fts (content_id, raw_text) VALUES (?, ?);",
                (content_id, raw_output),
            )
        self._db.commit()

        stub_text = (
            f"[Tool Output Intercepted: '{tool_name}' · {line_count} lines · {raw_bytes} bytes · Ref: {content_id}]\n"
            f"Digest: {summary_digest}\n"
            f"(Hint: Use ctx_search(query='...', content_id='{content_id}') to inspect verbatim content.)"
        )

        tokens_saved = max(
            0,
            int(raw_bytes / self.config.bytes_per_token_estimate)
            - int(len(stub_text.encode("utf-8")) / self.config.bytes_per_token_estimate),
        )

        stub = ToolOutputStub(
            content_id=content_id,
            tool_name=tool_name,
            stub_text=stub_text,
            raw_size_bytes=raw_bytes,
            tokens_saved=tokens_saved,
            line_count=line_count,
        )
        return stub_text, stub

    def ctx_search(
        self,
        query: str,
        content_id: str | None = None,
        limit: int | None = None,
    ) -> list[SearchResultSnippet]:
        """Query local FTS5 database for verbatim matching lines without inflating LLM context."""
        max_results = limit or self.config.max_search_results
        snippets: list[SearchResultSnippet] = []

        cursor = self._db.cursor()
        if content_id:
            cursor.execute(
                "SELECT raw_text FROM tool_outputs WHERE content_id = ?;",
                (content_id,),
            )
            row = cursor.fetchone()
            if not row:
                return []
            raw_text = str(row[0])
            matched_content_ids = [content_id]
        else:
            if self._fts_available:
                sanitized_query = query.replace('"', '""')
                cursor.execute(
                    "SELECT content_id FROM tool_outputs_fts WHERE raw_text MATCH ? LIMIT ?;",
                    (f'"{sanitized_query}"', max_results),
                )
                matched_content_ids = [str(r[0]) for r in cursor.fetchall()]
            else:
                cursor.execute(
                    "SELECT content_id FROM tool_outputs WHERE raw_text LIKE ? LIMIT ?;",
                    (f"%{query}%", max_results),
                )
                matched_content_ids = [str(r[0]) for r in cursor.fetchall()]

        lower_query = query.lower()
        for cid in matched_content_ids:
            cursor.execute("SELECT raw_text FROM tool_outputs WHERE content_id = ?;", (cid,))
            record = cursor.fetchone()
            if not record:
                continue
            text = str(record[0])
            for line_idx, line in enumerate(text.splitlines(), start=1):
                if lower_query in line.lower():
                    clean_snippet = line.strip()[: self.config.snippet_window_chars]
                    score = 1.0 if query in line else 0.8
                    snippets.append(
                        SearchResultSnippet(
                            content_id=cid,
                            line_number=line_idx,
                            snippet=clean_snippet,
                            match_score=score,
                        )
                    )
                    if len(snippets) >= max_results:
                        return snippets

        return snippets

    def trigger_hook(
        self,
        stage: ContextHookStage,
        session_id: str,
        payload: dict[str, str],
    ) -> LifecycleHookRecord:
        """Record lifecycle checkpoint across the five Context Mode stages."""
        metadata_str = json.dumps(payload, sort_keys=True)
        payload_digest = hashlib.sha256(metadata_str.encode("utf-8")).hexdigest()[:16]
        now = time.time()

        cursor = self._db.cursor()
        cursor.execute(
            """
            INSERT INTO lifecycle_hooks (
                stage, session_id, payload_digest, metadata_json, timestamp
            ) VALUES (?, ?, ?, ?, ?);
            """,
            (stage.value, session_id, payload_digest, metadata_str, now),
        )
        self._db.commit()

        return LifecycleHookRecord(
            stage=stage,
            session_id=session_id,
            payload_digest=payload_digest,
            metadata=payload,
            timestamp=now,
        )

    def get_lifecycle_history(self, session_id: str) -> list[LifecycleHookRecord]:
        """Fetch all recorded lifecycle hooks for a session in chronological order."""
        cursor = self._db.cursor()
        cursor.execute(
            """
            SELECT stage, session_id, payload_digest, metadata_json, timestamp
            FROM lifecycle_hooks WHERE session_id = ? ORDER BY id ASC;
            """,
            (session_id,),
        )
        records: list[LifecycleHookRecord] = []
        for row in cursor.fetchall():
            stage_str, sess, digest, meta_raw, ts = row
            records.append(
                LifecycleHookRecord(
                    stage=ContextHookStage(stage_str),
                    session_id=str(sess),
                    payload_digest=str(digest),
                    metadata=json.loads(meta_raw),
                    timestamp=float(ts),
                )
            )
        return records

    def close(self) -> None:
        """Close SQLite database connection cleanly."""
        self._db.close()
