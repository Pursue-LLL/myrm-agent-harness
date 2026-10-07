"""Unit tests for Full Archive Searchable History Meta-Tool and Engine.

Part of Item 127: FullArchiveSearchableHistoryMetaTool.
Verifies immutable message archiving, substring & token relevance scoring,
scoped filter queries, LangChain BaseTool execution, and thread safety.
"""

from __future__ import annotations

import concurrent.futures
import json

import pytest

from myrm_agent_harness.runtime.context.session_archive_search_engine import (
    InMemorySessionArchiveStore,
    SessionArchiveSearchEngine,
    create_search_session_archive_tool,
)
from myrm_agent_harness.runtime.context.session_archive_search_types import (
    ArchiveMessageRoleKind,
    ArchiveSearchFilter,
)


def test_archive_message_and_basic_search() -> None:
    """Verify appending message turns to archive and retrieving with exact matches."""
    store = InMemorySessionArchiveStore()
    engine = SessionArchiveSearchEngine(store=store)

    rec1 = engine.archive_message(
        session_id="sess-001",
        turn_index=1,
        role=ArchiveMessageRoleKind.USER,
        content="Please configure the OAuth redirect URI to http://localhost:8080/callback",
    )
    assert rec1.session_id == "sess-001"
    assert rec1.turn_index == 1

    engine.archive_message(
        session_id="sess-001",
        turn_index=2,
        role=ArchiveMessageRoleKind.TOOL_RESULT,
        content="Error 403: Invalid redirect_uri port binding on interface 127.0.0.1",
    )

    # Search for port binding error
    res = engine.search(query="port binding")
    assert res.total_matched >= 1
    assert res.items[0].record.turn_index == 2
    assert "port binding" in res.items[0].relevance_snippet.lower()
    assert res.items[0].match_score > 0.0


def test_search_filters_scoping() -> None:
    """Verify filtering by session_id, role, and turn range boundaries."""
    engine = SessionArchiveSearchEngine()

    for idx in range(1, 11):
        role = ArchiveMessageRoleKind.USER if idx % 2 == 1 else ArchiveMessageRoleKind.ASSISTANT
        engine.archive_message(
            session_id="sess-A",
            turn_index=idx,
            role=role,
            content=f"Message step {idx} discussing database migrations",
        )

    # 1. Filter by role USER only
    res_user = engine.search(
        query="database",
        filter_spec=ArchiveSearchFilter(
            session_id="sess-A",
            role_filters=[ArchiveMessageRoleKind.USER],
        ),
    )
    for it in res_user.items:
        assert it.record.role == ArchiveMessageRoleKind.USER

    # 2. Filter by turn range 3..6
    res_range = engine.search(
        query="database",
        filter_spec=ArchiveSearchFilter(
            session_id="sess-A",
            turn_range_start=3,
            turn_range_end=6,
        ),
    )
    assert len(res_range.items) <= 4
    for it in res_range.items:
        assert 3 <= it.record.turn_index <= 6

    # 3. Filter by non-existent session
    res_empty = engine.search(
        query="database",
        filter_spec=ArchiveSearchFilter(session_id="sess-B"),
    )
    assert res_empty.total_matched == 0


def test_create_search_session_archive_tool_sync() -> None:
    """Verify LangChain BaseTool synchronous invocation and JSON payload output."""
    engine = SessionArchiveSearchEngine()
    engine.archive_message(
        session_id="sess-tool",
        turn_index=15,
        role=ArchiveMessageRoleKind.USER,
        content="The client strictly requested TLS 1.3 only, do not allow TLS 1.2 fallback.",
    )

    archive_tool = create_search_session_archive_tool(engine=engine, locale="en")
    assert archive_tool.name == "search_session_archive"
    assert "Search through full" in archive_tool.description

    raw_json = archive_tool.invoke({
        "query": "TLS 1.3",
        "session_id": "sess-tool",
        "max_results": 3,
    })
    parsed = json.loads(raw_json)

    assert parsed["query"] == "TLS 1.3"
    assert parsed["total_matched"] >= 1
    assert len(parsed["items"]) >= 1
    item0 = parsed["items"][0]
    assert "TLS 1.3" in item0["record"]["content"]
    assert item0["record"]["turn_index"] == 15


@pytest.mark.asyncio
async def test_create_search_session_archive_tool_async() -> None:
    """Verify asynchronous invocation of the archive search tool."""
    engine = SessionArchiveSearchEngine()
    engine.archive_message(
        session_id="sess-async",
        turn_index=42,
        role=ArchiveMessageRoleKind.ERROR_LOG,
        content="CRITICAL: Deadlock detected in worker pool acquiring lock_id=db_trans_01",
    )

    tool_zh = create_search_session_archive_tool(engine=engine, locale="zh")
    assert "检索完整未压缩的历史对话档案" in tool_zh.description

    raw_json = await tool_zh.ainvoke({"query": "Deadlock detected"})
    parsed = json.loads(raw_json)

    assert parsed["total_matched"] >= 1
    assert "Deadlock detected" in parsed["items"][0]["relevance_snippet"]


def test_multithreaded_archive_and_search_concurrency() -> None:
    """Verify thread-safe concurrent archive writes and searches."""
    engine = SessionArchiveSearchEngine()

    def worker(worker_id: int) -> None:
        for step in range(20):
            sid = f"thread-sess-{worker_id}"
            engine.archive_message(
                session_id=sid,
                turn_index=step,
                role=ArchiveMessageRoleKind.USER,
                content=f"Worker {worker_id} token secret-{worker_id}-{step}",
            )
            res = engine.search(query=f"secret-{worker_id}")
            assert res.total_matched >= 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(16)]
        concurrent.futures.wait(futures)

    # Total messages written: 16 * 20 = 320
    all_res = engine.search(query="secret", filter_spec=ArchiveSearchFilter(max_results=50))
    assert all_res.total_matched == 320
