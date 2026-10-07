"""Engine and Meta-Tool Factory for Session Archive Search.

Part of Item 127: FullArchiveSearchableHistoryMetaTool.
Provides immutable historical dialogue recording, semantic and keyword recall,
and the callable search_session_archive meta-tool for retrieving historical dialogue.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import logging
import re
import threading
import uuid
from collections.abc import Sequence
from typing import Final, Protocol

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.runtime.context.session_archive_search_types import (
    ArchivedMessageRecord,
    ArchiveMessageRoleKind,
    ArchiveSearchFilter,
    ArchiveSearchResponse,
    ArchiveSearchResultItem,
)
from myrm_agent_harness.utils.locale import is_chinese

logger = logging.getLogger(__name__)

SEARCH_SESSION_ARCHIVE_DESC_EN: Final[str] = (
    "Search through full, uncompacted historical session archives. Use this tool when you need "
    "to recall exact user prompts from earlier turns, verbatim error traces, discarded options, "
    "or specific parameters that may have been lost in session handoffs or summaries."
)

SEARCH_SESSION_ARCHIVE_DESC_ZH: Final[str] = (
    "检索完整未压缩的历史对话档案。当需要精确找回数十轮前用户的原始要求原话、"
    "完整报错堆栈、被否决的具体配置或细节参数时调用此工具，避免摘要信息衰减带来的决策失误。"
)


class SessionArchiveRepositoryProtocol(Protocol):
    """Protocol for persisting and querying archived message records."""

    def append(self, record: ArchivedMessageRecord) -> None:
        """Append an immutable message record."""
        ...

    def query(self, filter_spec: ArchiveSearchFilter) -> Sequence[ArchivedMessageRecord]:
        """Query raw records matching the filter criteria."""
        ...


class InMemorySessionArchiveStore:
    """Thread-safe append-only in-memory archive store for session dialogues."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[ArchivedMessageRecord] = []

    def append(self, record: ArchivedMessageRecord) -> None:
        """Store an archived message record."""
        with self._lock:
            self._records.append(record)

    def query(self, filter_spec: ArchiveSearchFilter) -> Sequence[ArchivedMessageRecord]:
        """Filter records by session, role, and turn range."""
        with self._lock:
            records = list(self._records)

        matched: list[ArchivedMessageRecord] = []
        for r in records:
            if filter_spec.session_id is not None and r.session_id != filter_spec.session_id:
                continue
            if filter_spec.role_filters is not None and r.role not in filter_spec.role_filters:
                continue
            if filter_spec.turn_range_start is not None and r.turn_index < filter_spec.turn_range_start:
                continue
            if filter_spec.turn_range_end is not None and r.turn_index > filter_spec.turn_range_end:
                continue
            matched.append(r)
        return matched


class SessionArchiveSearchEngine:
    """Core search engine indexing and ranking archived dialogue messages."""

    def __init__(self, store: SessionArchiveRepositoryProtocol | None = None) -> None:
        self._store = store or InMemorySessionArchiveStore()

    def archive_message(
        self,
        session_id: str,
        turn_index: int,
        role: ArchiveMessageRoleKind,
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> ArchivedMessageRecord:
        """Archive a turn into the immutable repository."""
        record = ArchivedMessageRecord(
            record_id=f"rec-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            turn_index=turn_index,
            role=role,
            content=content,
            timestamp_iso=datetime.datetime.now(datetime.UTC).isoformat(),
            metadata=metadata or {},
        )
        self._store.append(record)
        return record

    def _extract_snippet(self, text: str, query: str, context_window: int = 80) -> str:
        """Extract a highlighted excerpt surrounding the best match point."""
        pos = text.lower().find(query.lower())
        if pos == -1:
            tokens = [t for t in re.split(r"\W+", query.lower()) if t]
            for token in tokens:
                pos = text.lower().find(token)
                if pos != -1:
                    break
        if pos == -1:
            return text[:context_window * 2].strip() + ("..." if len(text) > context_window * 2 else "")

        start = max(0, pos - context_window)
        end = min(len(text), pos + len(query) + context_window)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return f"{prefix}{text[start:end].strip()}{suffix}"

    def _compute_relevance(self, content: str, query: str) -> float:
        """Score message content relevance based on substring exactness and token overlap."""
        lower_content = content.lower()
        lower_query = query.lower().strip()
        if not lower_query:
            return 0.0

        score = 0.0
        # Exact full query match provides highest boost
        if lower_query in lower_content:
            score += 10.0

        query_tokens = set(re.findall(r"\w+", lower_query))
        if query_tokens:
            content_tokens = set(re.findall(r"\w+", lower_content))
            overlap = query_tokens.intersection(content_tokens)
            score += (len(overlap) / len(query_tokens)) * 5.0

        return round(score, 3)

    def search(
        self,
        query: str,
        filter_spec: ArchiveSearchFilter | None = None,
    ) -> ArchiveSearchResponse:
        """Search archived records and rank by calculated relevance."""
        effective_filter = filter_spec or ArchiveSearchFilter()
        candidates = self._store.query(effective_filter)

        scored_items: list[ArchiveSearchResultItem] = []
        for record in candidates:
            score = self._compute_relevance(record.content, query)
            if score > 0.0:
                snippet = self._extract_snippet(record.content, query)
                scored_items.append(
                    ArchiveSearchResultItem(
                        record=record,
                        match_score=score,
                        relevance_snippet=snippet,
                    )
                )

        scored_items.sort(key=lambda item: item.match_score, reverse=True)
        total_matched = len(scored_items)
        limited_items = scored_items[: effective_filter.max_results]

        return ArchiveSearchResponse(
            query=query,
            total_matched=total_matched,
            items=limited_items,
        )


def create_search_session_archive_tool(
    engine: SessionArchiveSearchEngine,
    locale: str = "en",
) -> BaseTool:
    """Factory creating the callable search_session_archive Meta-Tool for agents."""
    description = (
        SEARCH_SESSION_ARCHIVE_DESC_ZH if is_chinese(locale) else SEARCH_SESSION_ARCHIVE_DESC_EN
    )

    @tool("search_session_archive", description=description)
    def search_session_archive(
        query: str,
        session_id: str | None = None,
        role: str | None = None,
        max_results: int = 5,
    ) -> str:
        """Search uncompacted historical message archives by keywords or phrases.

        Args:
            query: Keyword, phrase, error message, or parameter to look up.
            session_id: Optional ID of the session archive to search.
            role: Optional role filter (user, assistant, tool_result, system, error_log).
            max_results: Maximum results to return (1-50, default 5).
        """
        role_filters = None
        if role:
            with contextlib.suppress(ValueError):
                role_filters = [ArchiveMessageRoleKind(role.lower().strip())]

        filter_spec = ArchiveSearchFilter(
            session_id=session_id,
            role_filters=role_filters,
            max_results=max(1, min(50, max_results)),
        )

        response = engine.search(query=query, filter_spec=filter_spec)
        return json.dumps(response.model_dump(mode="json"), ensure_ascii=False)

    return search_session_archive
