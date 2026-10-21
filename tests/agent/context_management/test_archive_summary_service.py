"""Tests for ArchiveSummaryService dispatch and metrics."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.runnables.config import RunnableConfig

from myrm_agent_harness.agent.context_management.archive_checkpoint import (
    ArchiveSummaryService,
    reset_archive_summary_pending_state,
)
from myrm_agent_harness.agent.context_management.archive_checkpoint.types import ArchiveCheckpointRecord
from myrm_agent_harness.agent.context_management.infra.schemas import CacheTtlPruneConfig
from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    clear_task_metrics,
    create_task_metrics,
)


def _large_content(chars: int = 20_000) -> str:
    return "x" * chars


@pytest.mark.asyncio
async def test_dispatch_skips_missing_chat_id() -> None:
    config = CacheTtlPruneConfig(archive_summary_enabled=True)
    service = ArchiveSummaryService(config=config, store=AsyncMock())
    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(),
        archive_path=".context/chat/compacted/out.txt",
        chat_id=None,
        summarizer_llm=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_dispatch_skips_store_unavailable() -> None:
    chat_id = "summary-no-store"
    clear_task_metrics(chat_id)
    metrics = create_task_metrics(chat_id)
    config = CacheTtlPruneConfig(archive_summary_enabled=True, archive_summary_min_tokens=1)
    service = ArchiveSummaryService(config=config, store=None)

    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(100),
        archive_path=".context/summary-no-store/compacted/out.txt",
        chat_id=chat_id,
        summarizer_llm=AsyncMock(),
    )

    assert metrics.archive_summary_skipped_count == 1
    assert metrics.archive_summary_skipped_reasons == {"store_unavailable": 1}


@pytest.mark.asyncio
async def test_dispatch_skips_summarizer_unavailable() -> None:
    chat_id = "summary-no-llm"
    clear_task_metrics(chat_id)
    metrics = create_task_metrics(chat_id)
    config = CacheTtlPruneConfig(archive_summary_enabled=True, archive_summary_min_tokens=1)
    service = ArchiveSummaryService(config=config, store=AsyncMock())

    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(100),
        archive_path=".context/summary-no-llm/compacted/out.txt",
        chat_id=chat_id,
        summarizer_llm=None,
    )

    assert metrics.archive_summary_skipped_count == 1
    assert metrics.archive_summary_skipped_reasons == {"summarizer_unavailable": 1}


@pytest.mark.asyncio
async def test_dispatch_skips_low_value_archive() -> None:
    chat_id = "summary-low-value"
    clear_task_metrics(chat_id)
    metrics = create_task_metrics(chat_id)
    config = CacheTtlPruneConfig(
        archive_summary_enabled=True,
        archive_summary_min_tokens=10_000,
    )
    service = ArchiveSummaryService(config=config, store=AsyncMock())

    service.dispatch(
        tool_name="grep_tool",
        content="short",
        archive_path=".context/summary-low-value/compacted/out.txt",
        chat_id=chat_id,
        summarizer_llm=AsyncMock(),
    )

    assert metrics.archive_summary_skipped_count == 1
    assert metrics.archive_summary_skipped_reasons == {"low_value_archive": 1}


def test_dispatch_skips_without_running_loop() -> None:
    chat_id = "summary-no-loop"
    clear_task_metrics(chat_id)
    metrics = create_task_metrics(chat_id)
    config = CacheTtlPruneConfig(archive_summary_enabled=True, archive_summary_min_tokens=1)
    service = ArchiveSummaryService(config=config, store=AsyncMock())

    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(100),
        archive_path=".context/summary-no-loop/compacted/out.txt",
        chat_id=chat_id,
        summarizer_llm=AsyncMock(),
    )

    assert metrics.archive_summary_skipped_count == 1
    assert metrics.archive_summary_skipped_reasons == {"no_running_loop": 1}


@pytest.mark.asyncio
async def test_dispatch_skips_duplicate_pending() -> None:
    chat_id = "summary-duplicate"
    clear_task_metrics(chat_id)
    create_task_metrics(chat_id)
    config = CacheTtlPruneConfig(
        archive_summary_enabled=True,
        archive_summary_min_tokens=1,
        archive_summary_max_queue_size=10,
    )
    mock_store = AsyncMock()

    async def _slow_store(**kwargs: object) -> ArchiveCheckpointRecord:
        await asyncio.sleep(0.5)
        return ArchiveCheckpointRecord(
            memory_id="mem-1",
            tool_name="grep_tool",
            archive_path=str(kwargs.get("archive_path", "")),
            summary="summary",
            chat_id=chat_id,
        )

    mock_store.store_checkpoint.side_effect = _slow_store
    service = ArchiveSummaryService(config=config, store=mock_store)
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(content="summary")
    reset_archive_summary_pending_state()
    archive_path = ".context/summary-duplicate/compacted/out.txt"

    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(100),
        archive_path=archive_path,
        chat_id=chat_id,
        summarizer_llm=mock_llm,
    )
    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(100),
        archive_path=archive_path,
        chat_id=chat_id,
        summarizer_llm=mock_llm,
    )

    await asyncio.sleep(0.6)
    metrics = create_task_metrics(chat_id)
    assert metrics.archive_summary_queued_count == 1
    assert metrics.archive_summary_skipped_reasons.get("duplicate_pending") == 1


@pytest.mark.asyncio
async def test_dispatch_skips_chat_queue_full() -> None:
    chat_id = "summary-chat-queue"
    clear_task_metrics(chat_id)
    create_task_metrics(chat_id)
    config = CacheTtlPruneConfig(
        archive_summary_enabled=True,
        archive_summary_min_tokens=1,
        archive_summary_max_queue_size=10,
        archive_summary_max_tasks_per_chat=1,
    )
    mock_store = AsyncMock()

    async def _slow_store(**kwargs: object) -> None:
        await asyncio.sleep(0.5)

    mock_store.store_checkpoint.side_effect = _slow_store
    service = ArchiveSummaryService(config=config, store=mock_store)
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(content="summary")
    reset_archive_summary_pending_state()

    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(100),
        archive_path=".context/summary-chat-queue/compacted/a.txt",
        chat_id=chat_id,
        summarizer_llm=mock_llm,
    )
    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(100),
        archive_path=".context/summary-chat-queue/compacted/b.txt",
        chat_id=chat_id,
        summarizer_llm=mock_llm,
    )

    await asyncio.sleep(0.05)
    metrics = create_task_metrics(chat_id)
    assert metrics.archive_summary_skipped_reasons.get("chat_queue_full") == 1


@pytest.mark.asyncio
async def test_dispatch_failure_records_metric() -> None:
    chat_id = "summary-failure"
    clear_task_metrics(chat_id)
    metrics = create_task_metrics(chat_id)
    config = CacheTtlPruneConfig(
        archive_summary_enabled=True,
        archive_summary_min_tokens=1,
        archive_summary_max_queue_size=10,
    )
    mock_store = AsyncMock()
    mock_store.store_checkpoint.side_effect = RuntimeError("store failed")
    service = ArchiveSummaryService(config=config, store=mock_store)
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(content="summary body")
    reset_archive_summary_pending_state()

    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(100),
        archive_path=".context/summary-failure/compacted/out.txt",
        chat_id=chat_id,
        summarizer_llm=mock_llm,
    )

    await asyncio.sleep(0.15)
    assert metrics.archive_summary_failed_count == 1


@pytest.mark.asyncio
async def test_dispatch_empty_summary_raises_and_records_failure() -> None:
    chat_id = "summary-empty"
    clear_task_metrics(chat_id)
    metrics = create_task_metrics(chat_id)
    config = CacheTtlPruneConfig(
        archive_summary_enabled=True,
        archive_summary_min_tokens=1,
        archive_summary_max_queue_size=10,
    )
    mock_store = AsyncMock()
    service = ArchiveSummaryService(config=config, store=mock_store)
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(content="   ")
    reset_archive_summary_pending_state()

    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(100),
        archive_path=".context/summary-empty/compacted/out.txt",
        chat_id=chat_id,
        summarizer_llm=mock_llm,
    )

    await asyncio.sleep(0.15)
    assert metrics.archive_summary_failed_count == 1
    mock_store.store_checkpoint.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_invokes_notifier_with_runnable_config() -> None:
    chat_id = "summary-notifier"
    clear_task_metrics(chat_id)
    create_task_metrics(chat_id)
    config = CacheTtlPruneConfig(
        archive_summary_enabled=True,
        archive_summary_min_tokens=1,
        archive_summary_max_queue_size=10,
    )
    record = ArchiveCheckpointRecord(
        memory_id="mem-1",
        tool_name="grep_tool",
        archive_path=".context/summary-notifier/compacted/out.txt",
        summary="summary",
        chat_id=chat_id,
    )
    mock_store = AsyncMock()
    mock_store.store_checkpoint.return_value = record
    captured: dict[str, object] = {}

    async def _notifier(
        checkpoint: ArchiveCheckpointRecord,
        run_config: RunnableConfig | None,
    ) -> None:
        captured["record"] = checkpoint
        captured["config"] = run_config

    service = ArchiveSummaryService(config=config, store=mock_store, on_checkpoint=_notifier)
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(content="summary body")
    runnable_config = RunnableConfig(configurable={"thread_id": chat_id})
    reset_archive_summary_pending_state()

    service.dispatch(
        tool_name="grep_tool",
        content=_large_content(100),
        archive_path=record.archive_path,
        chat_id=chat_id,
        summarizer_llm=mock_llm,
        runnable_config=runnable_config,
    )

    await asyncio.sleep(0.15)
    assert captured.get("record") == record
    assert captured.get("config") is runnable_config
