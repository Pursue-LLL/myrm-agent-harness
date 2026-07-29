"""Tests for wiki compile resilience (failure policy + circuit pause)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler
from myrm_agent_harness.toolkits.wiki.pipeline.queue import WikiIngestionQueue
from myrm_agent_harness.toolkits.wiki.pipeline.resilience import (
    evaluate_batch_pause,
    is_transient_error_kind,
    resolve_io_failure,
    resolve_llm_failure,
    sanitize_display_message,
)


@pytest.fixture
def mock_indexer() -> AsyncMock:
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    return indexer


def test_resolve_io_failure_not_retryable() -> None:
    resolution = resolve_io_failure("File not found")
    assert resolution.error_kind == "io_missing"
    assert resolution.retryable is False
    assert resolution.counts_toward_pause is False


def test_resolve_llm_auth_not_retryable() -> None:
    resolution = resolve_llm_failure(RuntimeError("Error 401 Unauthorized"))
    assert resolution.error_kind == ErrorKind.AUTH.value
    assert resolution.retryable is False
    assert resolution.counts_toward_pause is True


def test_evaluate_batch_pause_on_auth_cluster() -> None:
    should_pause, reason, kind = evaluate_batch_pause(
        success_count=0,
        failure_kinds=[ErrorKind.AUTH.value, ErrorKind.AUTH.value],
    )
    assert should_pause is True
    assert reason
    assert kind == ErrorKind.AUTH.value


def test_evaluate_batch_pause_on_mixed_auth_and_io() -> None:
    should_pause, reason, kind = evaluate_batch_pause(
        success_count=0,
        failure_kinds=[ErrorKind.AUTH.value, "io_missing"],
    )
    assert should_pause is True
    assert reason
    assert kind == ErrorKind.AUTH.value


def test_evaluate_batch_pause_on_mixed_auth_and_transient() -> None:
    should_pause, _, kind = evaluate_batch_pause(
        success_count=0,
        failure_kinds=[ErrorKind.AUTH.value, ErrorKind.RATE_LIMIT.value],
    )
    assert should_pause is True
    assert kind == ErrorKind.AUTH.value


def test_evaluate_batch_pause_skips_when_success() -> None:
    should_pause, _, _ = evaluate_batch_pause(success_count=1, failure_kinds=[ErrorKind.AUTH.value])
    assert should_pause is False


def test_is_transient_error_kind() -> None:
    assert is_transient_error_kind(ErrorKind.RATE_LIMIT.value) is True
    assert is_transient_error_kind(ErrorKind.AUTH.value) is False


def test_sanitize_display_message_redacts_api_key() -> None:
    cleaned = sanitize_display_message("Invalid key sk-abcdefghijklmnopqrstuvwxyz123456")
    assert "sk-" not in cleaned
    assert "[redacted]" in cleaned


def test_queue_mark_failed_stores_error_kind(tmp_path: Path) -> None:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    queue = WikiIngestionQueue(structure)
    queue.add_item("/tmp/example.md")
    item = queue.get_pending_items()[0]
    queue.mark_failed(item["id"], "401 Unauthorized", error_kind=ErrorKind.AUTH.value)
    failed = queue.get_failed_items(limit=1)[0]
    assert failed["error_kind"] == ErrorKind.AUTH.value


def test_queue_pause_and_resume(tmp_path: Path) -> None:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    queue = WikiIngestionQueue(structure)
    assert queue.is_compile_paused() is False
    queue.pause_compile("API auth failed", ErrorKind.AUTH.value)
    snapshot = queue.get_compile_run()
    assert snapshot.state == "paused"
    assert snapshot.primary_error_kind == ErrorKind.AUTH.value
    queue.resume_compile()
    assert queue.get_compile_run().state == "running"


@pytest.mark.asyncio
async def test_worker_pauses_on_auth_batch(tmp_path: Path, mock_indexer: AsyncMock) -> None:
    from unittest.mock import patch

    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    raw = structure.raw_dir / "doc.md"
    raw.write_text("# Title\n\nBody", encoding="utf-8")

    failing_llm = AsyncMock()
    failing_llm.ainvoke.side_effect = RuntimeError("401 Unauthorized")

    compiler = WikiCompiler(failing_llm, structure, WikiConfig(parallel_compilation=False), indexer=mock_indexer)
    compiler._queue.add_item(raw)

    with patch("asyncio.sleep", new=AsyncMock()):
        await compiler._worker_loop()

    assert compiler.get_compile_run().state == "paused"


@pytest.mark.asyncio
async def test_compile_all_skips_drain_when_paused(tmp_path: Path, mock_indexer: AsyncMock) -> None:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    raw = structure.raw_dir / "doc.md"
    raw.write_text("# Title\n\nBody", encoding="utf-8")

    llm = AsyncMock()
    llm.ainvoke.return_value = type("Resp", (), {"content": "[]"})()

    compiler = WikiCompiler(llm, structure, WikiConfig(), indexer=mock_indexer)
    compiler._queue.add_item(raw)
    compiler._queue.pause_compile("API auth failed", ErrorKind.AUTH.value)

    result = await compiler.compile_all(batch_size=5)

    assert result.concepts_count == 0
    assert result.articles_generated == 0
    llm.ainvoke.assert_not_called()
    assert compiler.get_compile_run().state == "paused"
