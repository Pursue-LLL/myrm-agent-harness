"""Unit tests for memory trace correlation and resolution (SessionCommitTraceIdExpose)."""

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.observability.tracing import TracingContext, resolve_current_trace_id
from myrm_agent_harness.toolkits.memory._internal.write_service import MemoryWriter
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.observability import MemoryOperationEvent, MemoryOperationKind, MemoryOperationStatus
from myrm_agent_harness.toolkits.memory.session import MemorySession
from myrm_agent_harness.toolkits.memory.types import (
    BaseMemory,
    MemoryScope,
    MemorySearchResult,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)


def test_resolve_current_trace_id_hierarchy():
    """Test trace ID resolution across OpenTelemetry and ContextVar fallbacks."""
    # 1. Test when neither OTel nor ContextVar is set
    with patch("myrm_agent_harness.infra.tracing.propagation.get_current_trace_id", return_value=None):
        token = TracingContext.set_trace_id("-")
        try:
            assert resolve_current_trace_id() is None
        finally:
            TracingContext.reset_trace_id(token)

    # 2. Test fallback to TracingContext ContextVar
    with patch("myrm_agent_harness.infra.tracing.propagation.get_current_trace_id", return_value=None):
        token = TracingContext.set_trace_id("ctx_trace_1234567890abcdef12345678")
        try:
            assert resolve_current_trace_id() == "ctx_trace_1234567890abcdef12345678"
        finally:
            TracingContext.reset_trace_id(token)

    # 3. Test OTel active span priority over ContextVar
    with patch(
        "myrm_agent_harness.infra.tracing.propagation.get_current_trace_id",
        return_value="otel_trace_1234567890abcdef12345678",
    ):
        token = TracingContext.set_trace_id("ctx_trace_fallback")
        try:
            assert resolve_current_trace_id() == "otel_trace_1234567890abcdef12345678"
        finally:
            TracingContext.reset_trace_id(token)


@pytest.mark.asyncio
async def test_memory_write_service_attaches_trace_id():
    """Test MemoryWriter automatically injects active trace_id on store."""
    token = TracingContext.set_trace_id("trace_commit_abcd1234")
    try:
        config = MemoryConfig(embedding_model="test-embedding", security_scan_enabled=False)
        scope = MemoryScope(namespaces=["global"])

        stored_memory: list[SemanticMemory] = []

        async def mock_store_semantic(mem: SemanticMemory) -> SemanticMemory:
            stored_memory.append(mem)
            return mem

        writer = MemoryWriter(
            config=config,
            scope=scope,
            namespaces=["global"],
            approval_required=False,
            bind_scope_func=lambda m: m,
            submit_pending_func=MagicMock(),
            store_semantic_func=mock_store_semantic,
            store_episodic_func=MagicMock(),
            store_procedural_func=MagicMock(),
            store_semantics_batch_func=MagicMock(),
            store_episodics_batch_func=MagicMock(),
            store_procedurals_batch_func=MagicMock(),
            store_conversations_batch_func=MagicMock(),
            deduplicate_semantic_batch_func=lambda mems: mems,
            deduplicate_episodic_batch_func=lambda mems: mems,
        )

        mem = SemanticMemory(content="User prefers dark mode", user_id="u1")
        assert mem.trace_id is None

        result = await writer.store(mem)
        assert result.trace_id == "trace_commit_abcd1234"
        assert len(stored_memory) == 1
        assert stored_memory[0].trace_id == "trace_commit_abcd1234"
    finally:
        TracingContext.reset_trace_id(token)


def test_memory_search_result_exposes_trace_id():
    """Test MemorySearchResult transparently exposes trace_id from inner memory."""
    mem = SemanticMemory(
        content="Important fact",
        user_id="u1",
        trace_id="search_trace_9876",
    )
    result = MemorySearchResult(
        memory=mem,
        score=0.95,
        memory_type=MemoryType.SEMANTIC,
    )
    assert result.trace_id == "search_trace_9876"
    assert result.content == "Important fact"


def test_memory_operation_event_trace_id_contract():
    """Test MemoryOperationEvent supports trace_id."""
    from datetime import datetime, timezone

    event = MemoryOperationEvent(
        id="evt_1",
        kind=MemoryOperationKind.WRITE,
        status=MemoryOperationStatus.SUCCESS,
        occurred_at=datetime.now(timezone.utc),
        memory_id="mem_1",
        trace_id="evt_trace_5566",
    )
    assert event.trace_id == "evt_trace_5566"
