"""A source is ``completed`` only when every article its concepts call for was written, not just extracted.

An article that fails to generate is a visible failure of the source behind it, so the queue panel can show it and
a retry can fix it, instead of a source that reads ``completed`` and has no article for ever.
"""

import asyncio
import json
import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedInputTooLargeError
from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler
from myrm_agent_harness.toolkits.wiki.pipeline.resilience import EMBED_WINDOW_VIOLATION
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

_SOURCES = ("alpha", "beta", "gamma")
_REAL_SLEEP = asyncio.sleep
_RATE_LIMITED = "429 rate limit exceeded"
_TOO_LONG = "This model's maximum context length is 8192 tokens, however you requested 9000"
_REJECTED = "401 Unauthorized: invalid api key"
_ARTICLE_FAILED = "Article generation failed"


class _StubLlm:
    """Extracts one concept named after the source plus ``shared``, which every source mentions; writes any article.

    ``failing`` maps a concept name to the error its article raises; clearing an entry is how the provider recovers.
    """

    def __init__(self, failing: dict[str, str]) -> None:
        self.failing = failing
        self.extracted_documents: list[str] = []

    async def ainvoke(self, messages: list[object]) -> AIMessage:
        prompt = str(getattr(messages[-1], "content", ""))
        if "# Document Content:" in prompt:
            document = prompt.rsplit("# Document Content:", 1)[1].strip()
            self.extracted_documents.append(document)
            topic = document.split()[0]
            concepts = [{"name": topic, "definition": f"about {topic}"}, {"name": "shared", "definition": "in common"}]
            return AIMessage(content=json.dumps(concepts))
        concept = prompt.split("\n", 1)[0].rsplit(": ", 1)[1]
        if concept in self.failing:
            raise RuntimeError(self.failing[concept])
        return AIMessage(content="## Compiled Truth\nstub article")


def _new_compiler(structure: WikiStructure, failing: dict[str, str], *, require_approval: bool = False) -> WikiCompiler:
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    indexer.extract_and_upsert_edges = MagicMock()
    compile_config = WikiCompileConfig(require_approval=require_approval, min_concept_mentions=1)
    return WikiCompiler(_StubLlm(failing), structure, WikiConfig(), compile_config, indexer=indexer)  # type: ignore[arg-type]


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    for name in _SOURCES:
        (structure.raw_dir / f"{name}.md").write_text(f"{name} is a topic worth compiling.")
    return structure


@pytest.fixture(autouse=True)
def _stop_background_workers() -> object:
    yield
    for task in WikiCompiler._active_workers.values():
        task.cancel()
    WikiCompiler._active_workers.clear()


async def _instant_sleep(_seconds: float) -> None:
    await _REAL_SLEEP(0)


async def _compile(compiler: WikiCompiler, entrypoint: str) -> None:
    """Drain the queue through ``compile_all`` or through the background worker, the two ways a compile runs."""
    if entrypoint == "compile_all":
        await compiler.compile_all()
        for task in WikiCompiler._active_workers.values():
            task.cancel()
        WikiCompiler._active_workers.clear()
        return
    await compiler.enqueue_changed_sources()
    with patch("asyncio.sleep", side_effect=_instant_sleep):
        await compiler._worker_loop()


def _rows(compiler: WikiCompiler) -> dict[str, dict[str, object]]:
    """The queue rows by source name."""
    with compiler._queue._get_conn() as conn:
        conn.row_factory = sqlite3.Row
        found = conn.execute("SELECT * FROM ingestion_queue").fetchall()
    return {Path(row["file_path"]).stem: dict(row) for row in found}


def _statuses(compiler: WikiCompiler) -> dict[str, str]:
    return {name: str(row["status"]) for name, row in _rows(compiler).items()}


def _article_exists(structure: WikiStructure, concept: str) -> bool:
    return structure.get_concept_file_path(concept).exists()


def _let_the_backoff_pass(compiler: WikiCompiler) -> None:
    with compiler._queue._get_conn() as conn:
        conn.execute(
            "UPDATE ingestion_queue SET retry_after = datetime('now', '-1 seconds') WHERE retry_after IS NOT NULL"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_a_source_whose_concept_article_was_rate_limited_is_failed_and_the_others_are_completed(
    wiki_structure: WikiStructure, entrypoint: str
) -> None:
    compiler = _new_compiler(wiki_structure, {"beta": _RATE_LIMITED})

    await _compile(compiler, entrypoint)

    assert _statuses(compiler) == {"alpha": "completed", "beta": "failed", "gamma": "completed"}
    beta = _rows(compiler)["beta"]
    assert beta["error_kind"] == ErrorKind.RATE_LIMIT.value
    assert beta["retry_count"] == 1
    assert beta["retry_after"]
    # The queue panel shows this text to the user; the provider's own message stays in the log.
    assert beta["error_message"] == _ARTICLE_FAILED
    assert not compiler._queue.is_compile_paused()
    assert [_article_exists(wiki_structure, name) for name in ("alpha", "beta", "gamma", "shared")] == [
        True,
        False,
        True,
        True,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_the_worker_writes_the_missing_article_once_the_backoff_has_passed(
    wiki_structure: WikiStructure, entrypoint: str
) -> None:
    compiler = _new_compiler(wiki_structure, {"beta": _RATE_LIMITED})
    await _compile(compiler, entrypoint)
    assert compiler._queue.get_transient_retryable_items() == []

    compiler._llm.failing.clear()  # type: ignore[attr-defined]
    _let_the_backoff_pass(compiler)
    assert [Path(item["file_path"]).stem for item in compiler._queue.get_transient_retryable_items()] == ["beta"]
    with patch("asyncio.sleep", side_effect=_instant_sleep):
        await compiler._worker_loop()

    assert _statuses(compiler) == {"alpha": "completed", "beta": "completed", "gamma": "completed"}
    assert _article_exists(wiki_structure, "beta")
    read = compiler._llm.extracted_documents  # type: ignore[attr-defined]
    assert sorted(doc.split()[0] for doc in read) == ["alpha", "beta", "beta", "gamma"]


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_an_article_failure_that_a_retry_cannot_fix_is_failed_without_an_automatic_retry(
    wiki_structure: WikiStructure, entrypoint: str
) -> None:
    compiler = _new_compiler(wiki_structure, {"beta": _TOO_LONG})

    await _compile(compiler, entrypoint)

    assert _statuses(compiler) == {"alpha": "completed", "beta": "failed", "gamma": "completed"}
    beta = _rows(compiler)["beta"]
    assert beta["error_kind"] == ErrorKind.CONTEXT_OVERFLOW.value
    assert not beta["retry_after"]
    _let_the_backoff_pass(compiler)
    assert compiler._queue.get_transient_retryable_items() == []
    assert not compiler._queue.is_compile_paused()


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_a_concept_mentioned_by_several_sources_fails_every_one_of_them(
    wiki_structure: WikiStructure, entrypoint: str
) -> None:
    compiler = _new_compiler(wiki_structure, {"shared": _RATE_LIMITED})

    await _compile(compiler, entrypoint)

    assert _statuses(compiler) == {"alpha": "failed", "beta": "failed", "gamma": "failed"}
    assert {row["error_kind"] for row in _rows(compiler).values()} == {ErrorKind.RATE_LIMIT.value}
    # What could be written was written; only the sources whose result is incomplete are failed.
    assert [_article_exists(wiki_structure, name) for name in ("alpha", "beta", "gamma", "shared")] == [
        True,
        True,
        True,
        False,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_a_source_with_a_permanent_and_a_transient_failure_is_not_retried_automatically(
    wiki_structure: WikiStructure, entrypoint: str
) -> None:
    compiler = _new_compiler(wiki_structure, {"alpha": _RATE_LIMITED, "shared": _TOO_LONG})

    await _compile(compiler, entrypoint)

    assert {row["error_kind"] for row in _rows(compiler).values()} == {ErrorKind.CONTEXT_OVERFLOW.value}
    _let_the_backoff_pass(compiler)
    assert compiler._queue.get_transient_retryable_items() == []


def _edit_alpha_when_the_first_article_is_written(
    compiler: WikiCompiler, structure: WikiStructure
) -> AbstractContextManager[object]:
    llm = compiler._llm
    answer = llm.ainvoke
    edits: list[str] = []

    async def edit_alpha_while_its_article_is_written(messages: list[object]) -> AIMessage:
        prompt = str(getattr(messages[-1], "content", ""))
        if not edits and "# Document Content:" not in prompt:
            (structure.raw_dir / "alpha.md").write_text("alpha is a topic that was rewritten.")
            edits.append("alpha")
        return await answer(messages)  # type: ignore[arg-type]

    return patch.object(llm, "ainvoke", edit_alpha_while_its_article_is_written)


@pytest.mark.asyncio
async def test_a_source_edited_while_its_article_failed_is_queued_again_not_failed(
    wiki_structure: WikiStructure,
) -> None:
    compiler = _new_compiler(wiki_structure, {"alpha": _RATE_LIMITED})

    with _edit_alpha_when_the_first_article_is_written(compiler, wiki_structure):
        await _compile(compiler, "compile_all")

    row = _rows(compiler)["alpha"]
    assert row["status"] == "pending"
    assert row["retry_count"] == 0


@pytest.mark.asyncio
async def test_the_edit_that_pre_empted_a_failure_is_compiled_by_the_same_worker_and_the_failure_is_counted_once(
    wiki_structure: WikiStructure,
) -> None:
    compiler = _new_compiler(wiki_structure, {"alpha": _RATE_LIMITED})

    with _edit_alpha_when_the_first_article_is_written(compiler, wiki_structure):
        await _compile(compiler, "worker")

    read = compiler._llm.extracted_documents  # type: ignore[attr-defined]
    assert [doc.split()[0] for doc in read].count("alpha") == 2
    alpha = _rows(compiler)["alpha"]
    assert alpha["status"] == "failed"
    assert alpha["retry_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_an_article_waiting_for_approval_counts_as_written(
    wiki_structure: WikiStructure, entrypoint: str
) -> None:
    compiler = _new_compiler(wiki_structure, {}, require_approval=True)

    await _compile(compiler, entrypoint)

    assert _statuses(compiler) == {"alpha": "completed", "beta": "completed", "gamma": "completed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_a_batch_whose_articles_were_all_rate_limited_pauses_the_circuit(
    wiki_structure: WikiStructure, entrypoint: str
) -> None:
    failing = dict.fromkeys((*_SOURCES, "shared"), _RATE_LIMITED)
    compiler = _new_compiler(wiki_structure, failing)

    await _compile(compiler, entrypoint)

    assert _statuses(compiler) == {"alpha": "failed", "beta": "failed", "gamma": "failed"}
    assert compiler._queue.is_compile_paused()
    assert compiler._queue.get_compile_run().primary_error_kind == ErrorKind.RATE_LIMIT.value


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_a_batch_whose_articles_the_provider_rejected_pauses_the_circuit(
    wiki_structure: WikiStructure, entrypoint: str
) -> None:
    failing = dict.fromkeys((*_SOURCES, "shared"), _REJECTED)
    compiler = _new_compiler(wiki_structure, failing)

    await _compile(compiler, entrypoint)

    assert _statuses(compiler) == {"alpha": "failed", "beta": "failed", "gamma": "failed"}
    assert compiler._queue.is_compile_paused()
    assert compiler._queue.get_compile_run().primary_error_kind == ErrorKind.AUTH.value
    _let_the_backoff_pass(compiler)
    assert compiler._queue.get_transient_retryable_items() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_a_staged_draft_counts_as_a_written_article_when_deciding_whether_to_pause(
    wiki_structure: WikiStructure, entrypoint: str
) -> None:
    failing = dict.fromkeys(_SOURCES, _RATE_LIMITED)
    compiler = _new_compiler(wiki_structure, failing, require_approval=True)

    await _compile(compiler, entrypoint)

    assert _statuses(compiler) == {"alpha": "failed", "beta": "failed", "gamma": "failed"}
    assert not compiler._queue.is_compile_paused()


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compile_all"])
async def test_the_pause_for_an_embed_window_violation_is_not_overwritten_by_the_one_for_failed_articles(
    wiki_structure: WikiStructure, monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    compiler = _new_compiler(wiki_structure, dict.fromkeys(_SOURCES, _RATE_LIMITED))

    async def too_large_to_embed(name: str, _content: str) -> None:
        raise EmbedInputTooLargeError(token_count=900, limit=512, model="test-embed", parent_key=name)

    monkeypatch.setattr(compiler._indexer, "upsert", too_large_to_embed)

    await _compile(compiler, entrypoint)

    assert _statuses(compiler) == {"alpha": "failed", "beta": "failed", "gamma": "failed"}
    assert compiler._queue.is_compile_paused()
    assert compiler._queue.get_compile_run().primary_error_kind == EMBED_WINDOW_VIOLATION
