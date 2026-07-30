"""Tests for PostCompactionRefetchGuardProcessor."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.post_compaction_refetch_guard_processor import (
    PostCompactionRefetchGuardProcessor,
)
from myrm_agent_harness.agent.context_management.tracking.task_metric_events import RefetchEvent
from myrm_agent_harness.agent.context_management.tracking.task_metrics_registry import (
    _store_lock,
    _task_metrics_store,
    create_task_metrics,
)


@pytest.fixture(autouse=True)
def _clear_metrics() -> None:
    with _store_lock:
        _task_metrics_store.clear()
    yield
    with _store_lock:
        _task_metrics_store.clear()


@pytest.mark.asyncio
async def test_injects_hint_when_archive_refetch_loops() -> None:
    chat_id = "chat-loop"
    metrics = create_task_metrics(chat_id)
    now = datetime.now(timezone.utc)
    for _ in range(2):
        metrics.refetch_events.append(
            RefetchEvent(
                timestamp=now,
                reason="archive_reference_read",
                tool_name="file_read_tool",
                estimated_tokens=100,
                archive_path=".context/chat-loop/offload/a.txt",
            )
        )

    processor = PostCompactionRefetchGuardProcessor()
    context = ProcessorContext(
        messages=[HumanMessage(content="hi")],
        user_query="hi",
        chat_id=chat_id,
        tokens_saved=500,
        metadata={},
    )

    assert await processor.should_process(context) is True
    updated = await processor.process(context)
    assert len(updated.messages) == 2
    assert "Repeated archive restores were detected" in str(updated.messages[-1].content)
    assert updated.metadata["post_compaction_refetch_guard_injected"] is True

    assert await processor.should_process(updated) is False


@pytest.mark.asyncio
async def test_skips_when_no_compaction_savings() -> None:
    processor = PostCompactionRefetchGuardProcessor()
    context = ProcessorContext(
        messages=[HumanMessage(content="hi")],
        user_query="hi",
        chat_id="chat-idle",
        tokens_saved=0,
        metadata={},
    )
    assert await processor.should_process(context) is False


def test_processor_name() -> None:
    processor = PostCompactionRefetchGuardProcessor()
    assert processor.name == "post_compaction_refetch_guard"


@pytest.mark.asyncio
async def test_skips_when_chat_id_missing() -> None:
    processor = PostCompactionRefetchGuardProcessor()
    context = ProcessorContext(
        messages=[HumanMessage(content="hi")],
        user_query="hi",
        chat_id=None,
        tokens_saved=100,
        metadata={},
    )
    assert await processor.should_process(context) is False
    unchanged = await processor.process(context)
    assert unchanged.messages == context.messages


@pytest.mark.asyncio
async def test_skips_when_metrics_missing() -> None:
    processor = PostCompactionRefetchGuardProcessor()
    context = ProcessorContext(
        messages=[HumanMessage(content="hi")],
        user_query="hi",
        chat_id="chat-without-metrics",
        tokens_saved=100,
        metadata={},
    )
    assert await processor.should_process(context) is True
    unchanged = await processor.process(context)
    assert len(unchanged.messages) == 1


@pytest.mark.asyncio
async def test_skips_when_refetch_events_do_not_loop() -> None:
    chat_id = "chat-no-loop"
    metrics = create_task_metrics(chat_id)
    now = datetime.now(timezone.utc)
    metrics.refetch_events.append(
        RefetchEvent(
            timestamp=now,
            reason="other_reason",
            tool_name="file_read_tool",
            estimated_tokens=100,
            archive_path=".context/chat-no-loop/offload/a.txt",
        )
    )
    metrics.refetch_events.append(
        RefetchEvent(
            timestamp=now,
            reason="archive_reference_read",
            tool_name="file_read_tool",
            estimated_tokens=100,
            archive_path="",
        )
    )

    processor = PostCompactionRefetchGuardProcessor()
    context = ProcessorContext(
        messages=[HumanMessage(content="hi")],
        user_query="hi",
        chat_id=chat_id,
        tokens_saved=100,
        metadata={},
    )
    unchanged = await processor.process(context)
    assert len(unchanged.messages) == 1
