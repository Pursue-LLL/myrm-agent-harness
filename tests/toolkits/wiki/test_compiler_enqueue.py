"""enqueue_changed_sources hands the sources to the queue and leaves the compiling to the background worker."""

import hashlib
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
    LAST_COMPILE_RAW_HASHES_KEY,
    raw_relative_storage_key,
)
from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline import compiler_enqueue
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler
from myrm_agent_harness.toolkits.wiki.pipeline.compiler_enqueue import filter_changed_files
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock()
    llm.ainvoke.side_effect = [
        AIMessage(content='[{"name": "ML", "definition": "Machine Learning"}]'),
        AIMessage(content="## Compiled Truth\nML article."),
    ]
    return llm


@pytest.fixture
def mock_indexer() -> AsyncMock:
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    indexer.extract_and_upsert_edges = MagicMock()
    return indexer


def _pending_names(compiler: WikiCompiler) -> list[str]:
    return sorted(Path(str(item["file_path"])).name for item in compiler._queue.get_pending_items(limit=50))


@pytest.mark.asyncio
async def test_new_sources_are_queued_without_a_single_model_call(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    (wiki_structure.raw_dir / "a.md").write_text("Machine learning is powerful.")
    (wiki_structure.raw_dir / "b.md").write_text("Data science content.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())

    queued = await compiler.enqueue_changed_sources()

    assert queued == 2
    assert _pending_names(compiler) == ["a.md", "b.md"]
    mock_llm.ainvoke.assert_not_called()
    assert compiler._queue.get_stats()["processing"] == 0


@pytest.mark.asyncio
async def test_a_second_call_queues_each_source_once(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    (wiki_structure.raw_dir / "a.md").write_text("Machine learning is powerful.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())

    await compiler.enqueue_changed_sources()
    await compiler.enqueue_changed_sources()

    assert _pending_names(compiler) == ["a.md"]


@pytest.mark.asyncio
async def test_an_incremental_compile_queues_only_what_changed_since_the_last_one(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    raw = wiki_structure.raw_dir / "a.md"
    raw.write_text("Machine learning is powerful.")
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), compile_config, indexer=mock_indexer)
    await compiler.compile_all()
    assert compiler._queue.get_stats()["pending"] == 0

    assert await compiler.enqueue_changed_sources() == 0
    assert _pending_names(compiler) == []

    raw.write_text("Machine learning is powerful, and so is deep learning.")
    assert await compiler.enqueue_changed_sources() == 1
    assert _pending_names(compiler) == ["a.md"]


@pytest.mark.asyncio
async def test_the_change_check_hashes_the_sources_off_the_event_loop_thread(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    (wiki_structure.raw_dir / "a.md").write_text("Machine learning is powerful.")
    (wiki_structure.raw_dir / "b.md").write_text("Data science content.")
    wiki_structure.get_wiki_metadata_path().write_text(json.dumps({}))
    hashing_threads: list[threading.Thread] = []
    real_sha256 = hashlib.sha256

    def spy_sha256(data: bytes = b"") -> "hashlib._Hash":
        hashing_threads.append(threading.current_thread())
        return real_sha256(data)

    monkeypatch.setattr(hashlib, "sha256", spy_sha256)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())

    assert await compiler.enqueue_changed_sources() == 2

    assert len(hashing_threads) == 2
    assert threading.main_thread() not in hashing_threads


@pytest.mark.asyncio
async def test_a_source_being_compiled_is_left_processing(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    (wiki_structure.raw_dir / "a.md").write_text("Machine learning is powerful.")
    (wiki_structure.raw_dir / "b.md").write_text("Data science content.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    await compiler.enqueue_changed_sources()
    in_flight = next(item for item in compiler._queue.get_pending_items() if Path(item["file_path"]).name == "a.md")
    compiler._queue.mark_processing(in_flight["id"])

    queued = await compiler.enqueue_changed_sources()

    assert queued == 1
    stats = compiler._queue.get_stats()
    assert (stats["processing"], stats["pending"]) == (1, 1)


@pytest.mark.asyncio
async def test_a_source_claimed_while_the_change_check_runs_is_left_processing(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    (wiki_structure.raw_dir / "a.md").write_text("Machine learning is powerful.")
    (wiki_structure.raw_dir / "b.md").write_text("Data science content.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    await compiler.enqueue_changed_sources()
    check_changed = compiler_enqueue.filter_changed_files

    async def worker_claims_a_while_checking(structure: WikiStructure, raw_files: list[Path]) -> list[Path]:
        changed = await check_changed(structure, raw_files)
        claimed = next(item for item in compiler._queue.get_pending_items() if Path(item["file_path"]).name == "a.md")
        compiler._queue.mark_processing(claimed["id"])
        return changed

    monkeypatch.setattr(compiler_enqueue, "filter_changed_files", worker_claims_a_while_checking)

    assert await compiler.enqueue_changed_sources() == 1
    stats = compiler._queue.get_stats()
    assert (stats["processing"], stats["pending"]) == (1, 1)


@pytest.mark.asyncio
async def test_a_full_compile_queues_every_source_again(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    (wiki_structure.raw_dir / "a.md").write_text("Machine learning is powerful.")
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(
        mock_llm, wiki_structure, WikiConfig(compile_strategy="full"), compile_config, indexer=mock_indexer
    )
    await compiler.compile_all()
    assert compiler._queue.get_stats()["pending"] == 0

    assert await compiler.enqueue_changed_sources() == 1
    assert _pending_names(compiler) == ["a.md"]


@pytest.mark.asyncio
async def test_nothing_is_queued_when_the_vault_has_no_sources(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())

    assert await compiler.enqueue_changed_sources() == 0
    assert compiler._queue.get_stats()["pending"] == 0


@pytest.mark.asyncio
async def test_every_source_counts_as_changed_before_the_first_compile(wiki_structure: WikiStructure) -> None:
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")

    assert await filter_changed_files(wiki_structure, [raw]) == [raw]


@pytest.mark.asyncio
async def test_a_source_whose_hash_matches_the_last_compile_is_unchanged(wiki_structure: WikiStructure) -> None:
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")
    known = {raw_relative_storage_key(wiki_structure, raw): hashlib.sha256(raw.read_bytes()).hexdigest()}
    wiki_structure.get_wiki_metadata_path().write_text(json.dumps({LAST_COMPILE_RAW_HASHES_KEY: known}))

    assert await filter_changed_files(wiki_structure, [raw]) == []


@pytest.mark.asyncio
async def test_a_source_whose_hash_differs_from_the_last_compile_is_changed(wiki_structure: WikiStructure) -> None:
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")
    known = {raw_relative_storage_key(wiki_structure, raw): "stale_hash"}
    wiki_structure.get_wiki_metadata_path().write_text(json.dumps({LAST_COMPILE_RAW_HASHES_KEY: known}))

    assert await filter_changed_files(wiki_structure, [raw]) == [raw]


@pytest.mark.asyncio
async def test_every_source_counts_as_changed_when_the_metadata_cannot_be_read(wiki_structure: WikiStructure) -> None:
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")
    wiki_structure.get_wiki_metadata_path().write_text("not valid json {{{")

    assert await filter_changed_files(wiki_structure, [raw]) == [raw]


@pytest.mark.asyncio
async def test_a_source_that_cannot_be_read_counts_as_changed(wiki_structure: WikiStructure) -> None:
    raw = wiki_structure.raw_dir / "ghost.md"
    raw.write_text("content")
    wiki_structure.get_wiki_metadata_path().write_text(
        json.dumps({LAST_COMPILE_RAW_HASHES_KEY: {"raw/ghost.md": "oldhash"}})
    )
    raw.unlink()

    assert await filter_changed_files(wiki_structure, [raw]) == [raw]
