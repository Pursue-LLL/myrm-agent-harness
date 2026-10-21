"""A source is ``completed`` only after all of its compile work is done, not when its concepts were extracted.

The queue is what the UI, the maintenance jobs and the daily-review rescue read to tell whether a compile is
still running, and what a restarted process uses to find the work a dead one left behind.
"""

import asyncio
import json
import re
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedInputTooLargeError
from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline import queue as queue_module
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

_SOURCES = ("alpha", "beta", "gamma")
_REAL_SLEEP = asyncio.sleep

# A real process that extracts the source's concepts and then dies without any cleanup, the way a kill -9 or a
# crash would while the articles are being written.
_KILLED_IN_POSTPROCESS = textwrap.dedent(
    """
    import asyncio
    import os
    import sys
    from pathlib import Path
    from unittest.mock import AsyncMock

    from langchain_core.messages import AIMessage

    from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
    from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler

    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content='[{"name": "alpha", "definition": "about alpha"}]')
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, WikiStructure(Path(sys.argv[1])), WikiConfig(), compile_config)


    async def die(*_args, **_kwargs):
        os._exit(137)


    compiler._generate_articles_batch = die
    asyncio.run(compiler.compile_all())
    """
)


class _StubLlm:
    """Answers the extraction of a source with one concept named after it, and every article with a fixed body."""

    def __init__(self) -> None:
        self.extracted_documents: list[str] = []

    async def ainvoke(self, messages: list[object]) -> AIMessage:
        prompt = str(getattr(messages[-1], "content", ""))
        if "# Document Content:" not in prompt:
            return AIMessage(content="## Compiled Truth\nstub article")
        document = prompt.rsplit("# Document Content:", 1)[1].strip()
        self.extracted_documents.append(document)
        topic = document.split()[0]
        return AIMessage(content=json.dumps([{"name": topic, "definition": f"about {topic}"}]))


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    for name in _SOURCES:
        (structure.raw_dir / f"{name}.md").write_text(f"{name} is a topic worth compiling.")
    return structure


def _new_compiler(structure: WikiStructure) -> WikiCompiler:
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    indexer.extract_and_upsert_edges = MagicMock()
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    return WikiCompiler(_StubLlm(), structure, WikiConfig(), compile_config, indexer=indexer)  # type: ignore[arg-type]


@pytest.fixture
def compiler(wiki_structure: WikiStructure) -> WikiCompiler:
    return _new_compiler(wiki_structure)


def _cancel_background_workers() -> None:
    for task in WikiCompiler._active_workers.values():
        task.cancel()
    WikiCompiler._active_workers.clear()


@pytest.fixture(autouse=True)
def _stop_background_workers() -> object:
    yield
    _cancel_background_workers()


async def _instant_sleep(_seconds: float) -> None:
    await _REAL_SLEEP(0)


async def _compile_from_the_queue(compiler: WikiCompiler, entrypoint: str) -> None:
    """Drain the queue through the background worker or through ``compile_all``, the two ways a compile runs."""
    if entrypoint == "compile_all":
        await compiler.compile_all()
        return
    await compiler.enqueue_changed_sources()
    with patch("asyncio.sleep", side_effect=_instant_sleep):
        await compiler._worker_loop()


def _observe(
    monkeypatch: pytest.MonkeyPatch,
    compiler: WikiCompiler,
    step: str,
    seen: dict[str, dict[str, int]],
) -> None:
    """Record the queue's counts at the moment ``step`` starts, then run it unchanged."""
    original = getattr(compiler, step)

    async def observing(*args: object, **kwargs: object) -> object:
        seen[step] = compiler._queue.get_stats()
        return await original(*args, **kwargs)

    monkeypatch.setattr(compiler, step, observing)


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_the_queue_reports_work_in_progress_until_the_whole_batch_is_done(
    compiler: WikiCompiler, monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    seen: dict[str, dict[str, int]] = {}
    for step in ("_generate_articles_batch", "_save_metadata", "_maybe_commit_vault_git"):
        _observe(monkeypatch, compiler, step, seen)

    await _compile_from_the_queue(compiler, entrypoint)

    working = {"pending": 0, "processing": 3, "completed": 0, "failed": 0}
    assert seen["_generate_articles_batch"] == working
    assert seen["_save_metadata"] == working
    # The vault snapshot backs the vault up; it is not part of any one source's results.
    assert seen["_maybe_commit_vault_git"] == {"pending": 0, "processing": 0, "completed": 3, "failed": 0}
    assert compiler._queue.get_stats() == {"pending": 0, "processing": 0, "completed": 3, "failed": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_a_source_whose_concepts_were_extracted_but_whose_postprocess_raised_is_failed_not_completed(
    compiler: WikiCompiler, monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    monkeypatch.setattr(compiler, "_save_metadata", AsyncMock(side_effect=RuntimeError("disk full")))

    if entrypoint == "compile_all":
        with pytest.raises(RuntimeError, match="disk full"):
            await compiler.compile_all()
    else:
        await _compile_from_the_queue(compiler, entrypoint)

    stats = compiler._queue.get_stats()
    assert (stats["completed"], stats["failed"], stats["processing"]) == (0, 3, 0)
    failed = compiler._queue.get_failed_items()
    assert {item["error_kind"] for item in failed} == {ErrorKind.UNKNOWN.value}
    assert {item["retry_count"] for item in failed} == {1}
    # The queue panel shows this text to the user, so it carries no internals of the raw exception.
    assert {item["error_message"] for item in failed} == {"Compile postprocess failed"}
    assert compiler._queue.get_transient_retryable_items() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_an_embed_pause_completes_the_sources_whose_articles_exist_and_takes_no_vault_snapshot(
    compiler: WikiCompiler, monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    async def too_large_to_embed(concept: ConceptInfo) -> str:
        raise EmbedInputTooLargeError(token_count=900, limit=512, model="test-embed", parent_key=concept.name)

    snapshot = AsyncMock()
    monkeypatch.setattr(compiler, "_generate_article", too_large_to_embed)
    monkeypatch.setattr(compiler, "_maybe_commit_vault_git", snapshot)

    await _compile_from_the_queue(compiler, entrypoint)

    assert compiler._queue.is_compile_paused()
    assert compiler._queue.get_stats() == {"pending": 0, "processing": 0, "completed": 3, "failed": 0}
    snapshot.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("entrypoint", "writes_metadata"), [("worker", False), ("compile_all", True)])
async def test_when_nothing_was_extracted_only_compile_all_still_refreshes_the_map_and_metadata(
    compiler: WikiCompiler, monkeypatch: pytest.MonkeyPatch, entrypoint: str, writes_metadata: bool
) -> None:
    monkeypatch.setattr(compiler, "_extract_concepts_from_doc", AsyncMock(return_value=[]))
    save_metadata = AsyncMock()
    monkeypatch.setattr(compiler, "_save_metadata", save_metadata)

    await _compile_from_the_queue(compiler, entrypoint)

    assert compiler._queue.get_stats() == {"pending": 0, "processing": 0, "completed": 0, "failed": 3}
    assert save_metadata.await_count == int(writes_metadata)


@pytest.mark.asyncio
async def test_a_transient_postprocess_failure_is_retried_by_the_worker_like_an_extraction_failure(
    compiler: WikiCompiler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compiler, "_save_metadata", AsyncMock(side_effect=RuntimeError("429 rate limit exceeded")))

    with pytest.raises(RuntimeError, match="rate limit"):
        await compiler.compile_all()

    failed = compiler._queue.get_failed_items()
    assert {item["error_kind"] for item in failed} == {ErrorKind.RATE_LIMIT.value}
    assert all(item["retry_after"] for item in failed)


@pytest.mark.asyncio
async def test_a_source_that_was_queued_again_while_its_batch_worked_stays_queued(
    compiler: WikiCompiler, wiki_structure: WikiStructure, monkeypatch: pytest.MonkeyPatch
) -> None:
    again = wiki_structure.raw_dir / "alpha.md"
    original = compiler._generate_articles_batch

    async def queue_alpha_again(*args: object, **kwargs: object) -> object:
        compiler._queue.add_item(again)
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(compiler, "_generate_articles_batch", queue_alpha_again)

    await compiler.compile_all()

    # compile_all hands the rest of the queue to a worker that has not run yet.
    assert compiler._queue.get_stats() == {"pending": 1, "processing": 0, "completed": 2, "failed": 0}
    assert compiler._queue.list_pending_file_paths() == [str(again)]


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_a_source_edited_while_its_batch_worked_is_compiled_again(
    compiler: WikiCompiler, wiki_structure: WikiStructure, monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    edited = wiki_structure.raw_dir / "alpha.md"
    original = compiler._generate_articles_batch
    edits: list[str] = []

    async def rewrite_alpha(*args: object, **kwargs: object) -> object:
        if not edits:
            edited.write_text("alpha is a topic that was rewritten.")
            edits.append("alpha")
            # A compile requested now cannot queue what the batch holds, so the edit has to be caught at the end.
            assert await compiler.enqueue_changed_sources() == 0
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(compiler, "_generate_articles_batch", rewrite_alpha)

    await _compile_from_the_queue(compiler, entrypoint)

    if entrypoint == "compile_all":
        # compile_all hands the rest of the queue to a worker that has not run yet; the test runs that drain itself.
        assert compiler._queue.get_stats() == {"pending": 1, "processing": 0, "completed": 2, "failed": 0}
        _cancel_background_workers()
        with patch("asyncio.sleep", side_effect=_instant_sleep):
            await compiler._worker_loop()

    assert compiler._queue.get_stats() == {"pending": 0, "processing": 0, "completed": 3, "failed": 0}
    alpha_read = [doc for doc in compiler._llm.extracted_documents if doc.startswith("alpha")]  # type: ignore[attr-defined]
    assert alpha_read == ["alpha is a topic worth compiling.", "alpha is a topic that was rewritten."]


@pytest.mark.asyncio
async def test_a_source_edited_while_its_concepts_were_being_extracted_is_compiled_again(
    compiler: WikiCompiler, wiki_structure: WikiStructure, monkeypatch: pytest.MonkeyPatch
) -> None:
    edited = wiki_structure.raw_dir / "alpha.md"
    llm = compiler._llm
    answer = llm.ainvoke
    edits: list[str] = []

    async def edit_during_the_model_call(messages: list[object]) -> AIMessage:
        # The model is answering about the text it was given; the file already differs from it.
        if not edits and "alpha is a topic worth compiling." in str(getattr(messages[-1], "content", "")):
            edited.write_text("alpha is a topic that was rewritten.")
            edits.append("alpha")
        return await answer(messages)  # type: ignore[arg-type]

    monkeypatch.setattr(llm, "ainvoke", edit_during_the_model_call)

    await _compile_from_the_queue(compiler, "worker")

    assert compiler._queue.get_stats() == {"pending": 0, "processing": 0, "completed": 3, "failed": 0}
    alpha_read = [doc for doc in llm.extracted_documents if doc.startswith("alpha")]  # type: ignore[attr-defined]
    assert alpha_read == ["alpha is a topic worth compiling.", "alpha is a topic that was rewritten."]


@pytest.mark.asyncio
async def test_a_source_deleted_while_its_batch_worked_is_still_completed(
    compiler: WikiCompiler, wiki_structure: WikiStructure, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = compiler._generate_articles_batch

    async def delete_alpha(*args: object, **kwargs: object) -> object:
        (wiki_structure.raw_dir / "alpha.md").unlink()
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(compiler, "_generate_articles_batch", delete_alpha)

    await compiler.compile_all()

    assert compiler._queue.get_stats() == {"pending": 0, "processing": 0, "completed": 3, "failed": 0}


@pytest.mark.asyncio
async def test_a_keep_alive_beat_that_fails_neither_stops_the_batch_nor_goes_unreported_to_the_loop(
    compiler: WikiCompiler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queue_module, "_HEARTBEAT_SECONDS", 0.01)
    locked = MagicMock(side_effect=sqlite3.OperationalError("database is locked"))
    monkeypatch.setattr(compiler._queue, "touch_processing", locked)
    original = compiler._generate_articles_batch

    async def slow_articles(*args: object, **kwargs: object) -> object:
        await _REAL_SLEEP(0.1)
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(compiler, "_generate_articles_batch", slow_articles)
    loop = asyncio.get_running_loop()
    unreported: list[dict[str, object]] = []
    loop.set_exception_handler(lambda _loop, context: unreported.append(context))
    try:
        await compiler.compile_all()
    finally:
        loop.set_exception_handler(None)

    assert compiler._queue.get_stats() == {"pending": 0, "processing": 0, "completed": 3, "failed": 0}
    assert locked.call_count >= 2
    assert unreported == []


@pytest.mark.asyncio
async def test_a_cancelled_batch_leaves_its_sources_processing_and_stops_its_keep_alive(
    compiler: WikiCompiler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queue_module, "_HEARTBEAT_SECONDS", 0.01)
    in_articles = asyncio.Event()

    async def stuck_articles(*_args: object, **_kwargs: object) -> object:
        in_articles.set()
        await asyncio.Event().wait()
        raise AssertionError("never reached")

    monkeypatch.setattr(compiler, "_generate_articles_batch", stuck_articles)
    task = asyncio.create_task(compiler.compile_all())
    await in_articles.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Not failed and not completed: the next process to open the queue requeues them.
    assert compiler._queue.get_stats() == {"pending": 0, "processing": 3, "completed": 0, "failed": 0}
    beats = MagicMock()
    monkeypatch.setattr(compiler._queue, "touch_processing", beats)
    await _REAL_SLEEP(0.05)
    beats.assert_not_called()


@pytest.mark.asyncio
async def test_a_batch_that_works_longer_than_the_stale_limit_is_not_taken_for_dead(
    compiler: WikiCompiler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queue_module, "_HEARTBEAT_SECONDS", 0.01)
    original = compiler._generate_articles_batch
    reaped: list[int] = []

    async def slow_articles(*args: object, **kwargs: object) -> object:
        # The batch has been silent for longer than the limit; only its heartbeat can say it is alive.
        with compiler._queue._get_conn() as conn:
            conn.execute("UPDATE ingestion_queue SET updated_at = datetime('now', '-400 seconds')")
        await _REAL_SLEEP(0.1)
        reaped.append(compiler._queue.reset_stale_processing())
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(compiler, "_generate_articles_batch", slow_articles)

    await compiler.compile_all()

    assert reaped == [0]
    assert compiler._queue.get_stats()["completed"] == 3


@pytest.mark.asyncio
async def test_a_source_a_killed_process_was_postprocessing_is_compiled_by_the_next_worker_without_a_user_click(
    wiki_structure: WikiStructure,
) -> None:
    for name in _SOURCES[1:]:
        (wiki_structure.raw_dir / f"{name}.md").unlink()
    result = subprocess.run(
        [sys.executable, "-c", _KILLED_IN_POSTPROCESS, str(wiki_structure.base_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 137, result.stderr
    assert not wiki_structure.get_concept_file_path("alpha").exists()

    # This process opens the queue database for the first time, as a restarted server would.
    restarted = WikiCompiler(
        _StubLlm(),  # type: ignore[arg-type]
        wiki_structure,
        WikiConfig(),
        WikiCompileConfig(require_approval=False, min_concept_mentions=1),
    )
    assert restarted._queue.get_stats() == {"pending": 1, "processing": 0, "completed": 0, "failed": 0}

    with patch("asyncio.sleep", side_effect=_instant_sleep):
        await restarted._worker_loop()

    assert wiki_structure.get_concept_file_path("alpha").exists()
    assert restarted._queue.get_stats() == {"pending": 0, "processing": 0, "completed": 1, "failed": 0}
    articles = [page.name for page in wiki_structure.concepts_dir.rglob("*.md") if not page.name.startswith(".")]
    assert articles == ["alpha.md"]


_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?")


def _vault_pages(structure: WikiStructure) -> dict[str, str]:
    """Everything the compile wrote under ``wiki/``, with the vault location and the clock taken out."""
    return {
        path.relative_to(structure.base_dir).as_posix(): _TIMESTAMP.sub(
            "<time>", path.read_text().replace(str(structure.base_dir), "<vault>")
        )
        for path in sorted(structure.wiki_dir.rglob("*"))
        if path.is_file()
    }


@pytest.mark.asyncio
async def test_the_worker_and_compile_all_compile_the_same_sources_to_the_same_vault(tmp_path: Path) -> None:
    vaults: dict[str, tuple[dict[str, str], dict[str, int]]] = {}
    for entrypoint in ("worker", "compile_all"):
        structure = WikiStructure(tmp_path / entrypoint)
        structure.ensure_structure()
        for name in _SOURCES:
            (structure.raw_dir / f"{name}.md").write_text(f"{name} is a topic worth compiling.")
        compiler = _new_compiler(structure)
        await _compile_from_the_queue(compiler, entrypoint)
        vaults[entrypoint] = (_vault_pages(structure), compiler._queue.get_stats())

    worker_pages, worker_queue = vaults["worker"]
    compile_all_pages, compile_all_queue = vaults["compile_all"]
    assert "wiki/concepts/alpha.md" in worker_pages
    assert worker_pages == compile_all_pages
    assert worker_queue == compile_all_queue == {"pending": 0, "processing": 0, "completed": 3, "failed": 0}
