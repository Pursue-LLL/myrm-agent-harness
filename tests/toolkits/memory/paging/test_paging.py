"""Unit tests for Agent-Driven Memory Paging with Hard Boundary Governance."""

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.paging import (
    AccessViolationError,
    AgentMemoryPagingEngine,
    HardBoundaryScopeGateway,
    HardScopeContext,
    MemoryPageQuery,
    MemoryPageRecord,
    PagingBudgetExceededError,
    PagingBudgetPolicy,
)


@pytest.fixture
def base_context() -> HardScopeContext:
    """Fixture providing an authorized physical scope context."""
    return HardScopeContext(
        tenant_id="tenant-alpha",
        user_id="user-123",
        project_id="proj-ai-agent",
        session_id="session-xyz-1",
    )


@pytest.fixture
def foreign_context() -> HardScopeContext:
    """Fixture providing a distinct isolated physical scope context."""
    return HardScopeContext(
        tenant_id="tenant-beta",
        user_id="user-999",
        project_id="proj-secret",
        session_id="session-xyz-2",
    )


def test_basic_cursor_pagination(base_context: HardScopeContext) -> None:
    """Test sequential cursor navigation across multiple pages."""
    engine = AgentMemoryPagingEngine()
    now = datetime.now(UTC)

    # Insert 12 records
    records: list[MemoryPageRecord] = [
        MemoryPageRecord(
            record_id=f"rec-{i}",
            scope=base_context,
            content=f"Memory chunk index {i}",
            tags=["fact"],
            token_count=10,
            created_at=now + timedelta(seconds=i),
        )
        for i in range(12)
    ]
    engine.insert_records(records)
    assert engine.total_records == 12

    # Query page 1 (size 5)
    page1 = engine.query_page(MemoryPageQuery(page_size=5), base_context)
    assert len(page1.records) == 5
    assert page1.has_more is True
    assert page1.next_cursor is not None
    assert page1.page_index == 0
    assert page1.records[0].record_id == "rec-0"
    assert page1.records[4].record_id == "rec-4"
    assert page1.page_token_cost == 50

    # Query page 2 (size 5) using next_cursor
    page2 = engine.query_page(
        MemoryPageQuery(cursor=page1.next_cursor, page_size=5),
        base_context,
    )
    assert len(page2.records) == 5
    assert page2.has_more is True
    assert page2.page_index == 1
    assert page2.records[0].record_id == "rec-5"
    assert page2.records[4].record_id == "rec-9"

    # Query page 3 (remaining 2 items)
    page3 = engine.query_page(
        MemoryPageQuery(cursor=page2.next_cursor, page_size=5),
        base_context,
    )
    assert len(page3.records) == 2
    assert page3.has_more is False
    assert page3.next_cursor is None
    assert page3.page_index == 2
    assert page3.records[0].record_id == "rec-10"
    assert page3.records[1].record_id == "rec-11"


def test_hard_boundary_isolation(
    base_context: HardScopeContext,
    foreign_context: HardScopeContext,
) -> None:
    """Ensure records from another tenant or project are never visible."""
    engine = AgentMemoryPagingEngine()
    now = datetime.now(UTC)

    # Insert records into alpha
    engine.insert_record(
        MemoryPageRecord(
            record_id="rec-alpha",
            scope=base_context,
            content="Alpha project secrets",
            token_count=15,
            created_at=now,
        )
    )
    # Insert records into beta
    engine.insert_record(
        MemoryPageRecord(
            record_id="rec-beta",
            scope=foreign_context,
            content="Beta project secrets",
            token_count=20,
            created_at=now,
        )
    )

    # Query from alpha context
    res_alpha = engine.query_page(MemoryPageQuery(page_size=10), base_context)
    assert len(res_alpha.records) == 1
    assert res_alpha.records[0].record_id == "rec-alpha"

    # Query from beta context
    res_beta = engine.query_page(MemoryPageQuery(page_size=10), foreign_context)
    assert len(res_beta.records) == 1
    assert res_beta.records[0].record_id == "rec-beta"


def test_forged_project_boundary_violation(base_context: HardScopeContext) -> None:
    """Agent attempting to inject a cross-project purported ID must be intercepted."""
    gateway = HardBoundaryScopeGateway()
    engine = AgentMemoryPagingEngine(gateway=gateway)

    # Purport accessing forbidden project
    query = MemoryPageQuery(
        page_size=5,
        purported_project_id="unauthorized-competitor-proj",
    )

    with pytest.raises(AccessViolationError, match="outside authorized physical scope"):
        engine.query_page(query, base_context)

    # Verify audit logs captured the violation
    audits = gateway.audit_logs
    assert len(audits) == 1
    assert audits[0].session_id == base_context.session_id
    assert "unauthorized-competitor-proj" in audits[0].attempted_scope
    assert base_context.project_id in audits[0].actual_scope

    # Clear audit log test
    gateway.clear_audit_logs()
    assert len(gateway.audit_logs) == 0


def test_paging_budget_page_count_limit(base_context: HardScopeContext) -> None:
    """Enforce page query count limit per session."""
    engine = AgentMemoryPagingEngine()
    now = datetime.now(UTC)

    for i in range(10):
        engine.insert_record(
            MemoryPageRecord(
                record_id=f"r-{i}",
                scope=base_context,
                content=f"item {i}",
                token_count=5,
                created_at=now + timedelta(seconds=i),
            )
        )

    # Restrict session budget to max 2 queries
    policy = PagingBudgetPolicy(max_pages_per_session=2, max_tokens_per_session=1000)
    engine.set_session_budget_policy(base_context.session_id, policy)

    # Query 1
    engine.query_page(MemoryPageQuery(page_size=1), base_context)
    # Query 2
    engine.query_page(MemoryPageQuery(page_size=1), base_context)

    # Query 3 should be blocked by budget
    with pytest.raises(PagingBudgetExceededError, match="exceeded maximum page query allowance"):
        engine.query_page(MemoryPageQuery(page_size=1), base_context)


def test_paging_budget_token_limit(base_context: HardScopeContext) -> None:
    """Enforce cumulative token budget per session."""
    engine = AgentMemoryPagingEngine()
    now = datetime.now(UTC)

    # Insert items with 100 tokens each
    for i in range(5):
        engine.insert_record(
            MemoryPageRecord(
                record_id=f"heavy-{i}",
                scope=base_context,
                content=f"Heavy content {i}",
                token_count=100,
                created_at=now + timedelta(seconds=i),
            )
        )

    # Policy with 150 token budget
    policy = PagingBudgetPolicy(max_pages_per_session=10, max_tokens_per_session=150)
    engine.set_session_budget_policy(base_context.session_id, policy)

    # First query consumes 100 tokens (allowed)
    res1 = engine.query_page(MemoryPageQuery(page_size=1), base_context)
    assert res1.page_token_cost == 100

    # Second query would check if budget is already exhausted.
    # Note: engine checks budget.used_tokens >= budget.max_tokens_per_session before fetching.
    # used is 100 < 150, so second query executes and consumes another 100 -> used = 200.
    res2 = engine.query_page(MemoryPageQuery(page_size=1), base_context)
    assert res2.page_token_cost == 100

    # Third query sees used_tokens (200) >= max_tokens (150) -> raises PagingBudgetExceededError
    with pytest.raises(PagingBudgetExceededError, match="exceeded cumulative token budget"):
        engine.query_page(MemoryPageQuery(page_size=1), base_context)


def test_text_and_tag_filtering(base_context: HardScopeContext) -> None:
    """Test combined keyword and tag-based filtering."""
    engine = AgentMemoryPagingEngine()
    now = datetime.now(UTC)

    engine.insert_record(
        MemoryPageRecord(
            record_id="r1",
            scope=base_context,
            content="PostgreSQL database cluster config",
            tags=["infra", "database"],
            token_count=10,
            created_at=now,
        )
    )
    engine.insert_record(
        MemoryPageRecord(
            record_id="r2",
            scope=base_context,
            content="Redis caching layer config",
            tags=["infra", "cache"],
            token_count=10,
            created_at=now + timedelta(seconds=1),
        )
    )
    engine.insert_record(
        MemoryPageRecord(
            record_id="r3",
            scope=base_context,
            content="Frontend React routing setup",
            tags=["ui", "frontend"],
            token_count=10,
            created_at=now + timedelta(seconds=2),
        )
    )

    # Filter by tag 'infra'
    tag_res = engine.query_page(
        MemoryPageQuery(page_size=10, filter_tags=["infra"]),
        base_context,
    )
    assert len(tag_res.records) == 2
    assert {r.record_id for r in tag_res.records} == {"r1", "r2"}

    # Filter by text 'cluster'
    text_res = engine.query_page(
        MemoryPageQuery(page_size=10, query_text="Cluster"),
        base_context,
    )
    assert len(text_res.records) == 1
    assert text_res.records[0].record_id == "r1"


def test_corrupted_cursor_handling(base_context: HardScopeContext) -> None:
    """Corrupted or invalid base64 cursor should gracefully fall back to offset 0."""
    engine = AgentMemoryPagingEngine()
    now = datetime.now(UTC)

    engine.insert_record(
        MemoryPageRecord(
            record_id="r0",
            scope=base_context,
            content="Initial entry",
            token_count=5,
            created_at=now,
        )
    )

    res = engine.query_page(
        MemoryPageQuery(cursor="corrupted-non-base64-token!!", page_size=5),
        base_context,
    )
    assert len(res.records) == 1
    assert res.records[0].record_id == "r0"
    assert res.page_index == 0
