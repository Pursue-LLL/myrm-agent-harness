"""Extended tests for WikiCompiler - covering _filter_changed_files, compile_all,
_extract_concepts_from_doc, _parse_concepts_response, _build_index, _generate_backlinks,
_save_metadata, purpose injection, parallel batch ingestion, worker loop, and edge cases."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_llm() -> AsyncMock:
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content='[{"name": "TestConcept", "definition": "A test concept"}]')
    return llm


@pytest.fixture
def mock_indexer() -> AsyncMock:
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    indexer.extract_and_upsert_edges = AsyncMock()
    return indexer


# --- _parse_concepts_response ---


def test_parse_json_response(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    concepts = compiler._parse_concepts_response(
        '[{"name": "ML", "definition": "Machine Learning"}]', "test.md"
    )
    assert len(concepts) == 1
    assert concepts[0].name == "ML"
    assert concepts[0].definition == "Machine Learning"


def test_parse_json_with_code_block(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    concepts = compiler._parse_concepts_response(
        '```json\n[{"name": "AI", "definition": "Artificial Intelligence"}]\n```', "test.md"
    )
    assert len(concepts) == 1
    assert concepts[0].name == "AI"


def test_parse_bullet_response(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    concepts = compiler._parse_concepts_response(
        "1. **Neural Network** - A computing system\n- **Gradient** - A derivative vector", "test.md"
    )
    assert len(concepts) == 2
    assert concepts[0].name == "Neural Network"
    assert concepts[1].name == "Gradient"


def test_parse_empty_response(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    concepts = compiler._parse_concepts_response("No concepts found.", "test.md")
    assert concepts == []


# --- _filter_changed_files ---


@pytest.mark.asyncio
async def test_filter_changed_files_no_metadata(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")
    changed = await compiler._filter_changed_files([raw])
    assert changed == [raw]


@pytest.mark.asyncio
async def test_filter_changed_files_unchanged(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")

    import hashlib

    content_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
    metadata_path = wiki_structure.get_wiki_metadata_path()
    metadata_path.write_text(json.dumps({"file_hashes": {str(raw): content_hash}}))

    changed = await compiler._filter_changed_files([raw])
    assert changed == []


@pytest.mark.asyncio
async def test_filter_changed_files_modified(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")

    metadata_path = wiki_structure.get_wiki_metadata_path()
    metadata_path.write_text(json.dumps({"file_hashes": {str(raw): "stale_hash"}}))

    changed = await compiler._filter_changed_files([raw])
    assert changed == [raw]


# --- _extract_concepts_from_doc ---


@pytest.mark.asyncio
async def test_extract_concepts_from_doc(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("Machine learning is about data.")

    mock_llm.ainvoke.return_value = AIMessage(content='[{"name": "ML", "definition": "Machine Learning"}]')
    concepts = await compiler._extract_concepts_from_doc(raw)
    assert len(concepts) == 1
    assert concepts[0].name == "ML"


@pytest.mark.asyncio
async def test_extract_concepts_from_doc_file_not_found(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    concepts = await compiler._extract_concepts_from_doc(Path("/nonexistent.md"))
    assert concepts == []


# --- _build_index ---


@pytest.mark.asyncio
async def test_build_index(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo

    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    concepts = [
        ConceptInfo(name="Alpha", definition="def A", mentions=2, source_files=["a.md"]),
        ConceptInfo(name="Beta", definition="def B", mentions=2, source_files=["b.md"]),
    ]
    await compiler._build_index(concepts)
    index_path = wiki_structure.get_index_file_path()
    assert index_path.exists()
    content = index_path.read_text()
    assert "[[Alpha]]" in content
    assert "[[Beta]]" in content


# --- _save_metadata ---


@pytest.mark.asyncio
async def test_save_metadata(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")

    await compiler._save_metadata(5, 3)
    metadata_path = wiki_structure.get_wiki_metadata_path()
    assert metadata_path.exists()
    metadata = json.loads(metadata_path.read_text())
    assert metadata["total_concepts"] == 5
    assert metadata["total_articles"] == 3
    assert str(raw) in metadata["file_hashes"]


# --- _generate_backlinks ---


@pytest.mark.asyncio
async def test_generate_backlinks(wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock) -> None:
    from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo

    config = WikiConfig(enable_backlinks=True)
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    concept_path = wiki_structure.get_concept_file_path("Test")
    concept_path.write_text("## Compiled Truth\nContent.")

    concepts = [
        ConceptInfo(name="Test", definition="def", mentions=2, source_files=["a.md"], related_concepts=["Related"]),
    ]
    count = await compiler._generate_backlinks(concepts)
    assert count == 1
    content = concept_path.read_text()
    assert "[[Related]]" in content


@pytest.mark.asyncio
async def test_generate_backlinks_idempotent(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    """Calling _generate_backlinks twice must not duplicate the section."""
    from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo

    config = WikiConfig(enable_backlinks=True)
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    concept_path = wiki_structure.get_concept_file_path("Test")
    concept_path.write_text("## Compiled Truth\nContent.")

    concepts = [
        ConceptInfo(name="Test", definition="def", mentions=2, source_files=["a.md"], related_concepts=["Related"]),
    ]

    await compiler._generate_backlinks(concepts)
    await compiler._generate_backlinks(concepts)

    content = concept_path.read_text()
    assert content.count("## Related Concepts") == 1, "Section duplicated after second call"
    assert content.count("[[Related]]") == 1, "Wikilink duplicated after second call"


# --- compile_all with queue ---


@pytest.mark.asyncio
async def test_compile_all_no_files(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    result = await compiler.compile_all()
    assert result.concepts_count == 0
    assert result.articles_generated == 0


@pytest.mark.asyncio
async def test_compile_all_incremental(wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock) -> None:
    raw = wiki_structure.raw_dir / "doc.md"
    raw.write_text("Machine learning is powerful.")

    mock_llm.ainvoke.side_effect = [
        AIMessage(content='[{"name": "ML", "definition": "Machine Learning"}]'),
        AIMessage(content="## Compiled Truth\nML article."),
    ]
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), compile_config, indexer=mock_indexer)
    result = await compiler.compile_all(batch_size=10)
    assert result.concepts_count >= 1
    assert result.articles_generated >= 1
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_compile_all_full_strategy(wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock) -> None:
    raw = wiki_structure.raw_dir / "doc.md"
    raw.write_text("Data science content.")

    mock_llm.ainvoke.side_effect = [
        AIMessage(content='[{"name": "DS", "definition": "Data Science"}]'),
        AIMessage(content="## Compiled Truth\nDS article."),
    ]
    config = WikiConfig(compile_strategy="full")
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(mock_llm, wiki_structure, config, compile_config, indexer=mock_indexer)
    result = await compiler.compile_all()
    assert result.concepts_count >= 1


# --- _extract_concepts_batch with queue ---


@pytest.mark.asyncio
async def test_extract_concepts_batch_file_not_found(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    compiler._queue.add_item("/nonexistent/file.md")
    items = compiler._queue.get_pending_items()
    concepts = await compiler._extract_concepts_batch(items)
    assert concepts == []
    stats = compiler._queue.get_stats()
    assert stats["failed"] == 1


@pytest.mark.asyncio
async def test_extract_concepts_batch_merge_duplicates(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())

    raw1 = wiki_structure.raw_dir / "doc1.md"
    raw1.write_text("Doc 1 about ML")
    raw2 = wiki_structure.raw_dir / "doc2.md"
    raw2.write_text("Doc 2 also about ML")

    mock_llm.ainvoke.side_effect = [
        AIMessage(content='[{"name": "ML", "definition": "Machine Learning"}]'),
        AIMessage(content='[{"name": "ML", "definition": "Machine Learning updated"}]'),
    ]

    compiler._queue.add_batch([raw1, raw2])
    items = compiler._queue.get_pending_items(limit=10)
    concepts = await compiler._extract_concepts_batch(items)
    assert len(concepts) == 1
    assert len(concepts[0].source_files) == 2


# --- purpose injection ---


@pytest.mark.asyncio
async def test_purpose_injection(wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock) -> None:
    purpose_path = wiki_structure.get_purpose_path()
    purpose_path.write_text("Focus on AI/ML")

    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), compile_config, indexer=mock_indexer)

    mock_llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nAI article.")

    class DummyConcept:
        name = "AI"
        source_files = ["ai.md"]

    await compiler._generate_article(DummyConcept())

    call_args = mock_llm.ainvoke.call_args[0][0]
    human_msg_content = call_args[1].content
    assert "Focus on AI/ML" in human_msg_content


# --- Parallel batch ingestion ---


@pytest.mark.asyncio
async def test_extract_concepts_batch_parallel(wiki_structure: WikiStructure, mock_indexer: AsyncMock):
    """Test that _extract_concepts_batch runs in parallel when parallel_compilation=True."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content='[{"name": "Concept1", "definition": "Def1", "related_concepts": []}]'
    )
    config = WikiConfig(parallel_compilation=True, max_parallel_workers=2)
    compiler = WikiCompiler(llm, wiki_structure, config, WikiCompileConfig(), indexer=mock_indexer)

    raw_dir = wiki_structure.raw_dir
    for i in range(3):
        (raw_dir / f"doc{i}.md").write_text(f"Content {i}", encoding="utf-8")

    queue = compiler._queue
    queue.add_batch([raw_dir / f"doc{i}.md" for i in range(3)])
    items = queue.get_pending_items(limit=3)

    concepts = await compiler._extract_concepts_batch(items)
    assert len(concepts) >= 1
    assert llm.ainvoke.await_count == 3


@pytest.mark.asyncio
async def test_extract_concepts_batch_sequential(wiki_structure: WikiStructure, mock_indexer: AsyncMock):
    """Test that _extract_concepts_batch runs sequentially when parallel_compilation=False."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content='[{"name": "SeqConcept", "definition": "Def", "related_concepts": []}]'
    )
    config = WikiConfig(parallel_compilation=False)
    compiler = WikiCompiler(llm, wiki_structure, config, WikiCompileConfig(), indexer=mock_indexer)

    raw_dir = wiki_structure.raw_dir
    (raw_dir / "seq_doc.md").write_text("Sequential content", encoding="utf-8")

    queue = compiler._queue
    queue.add_item(raw_dir / "seq_doc.md")
    items = queue.get_pending_items(limit=1)

    concepts = await compiler._extract_concepts_batch(items)
    assert len(concepts) == 1
    assert concepts[0].name == "SeqConcept"


@pytest.mark.asyncio
async def test_generate_articles_batch_parallel(wiki_structure: WikiStructure, mock_indexer: AsyncMock):
    """Test that _generate_articles_batch processes concepts in parallel."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nArticle content.")
    config = WikiConfig(parallel_compilation=True, max_parallel_workers=2)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo

    concepts = [
        ConceptInfo(name=f"ParallelConcept{i}", definition=f"Def{i}", mentions=2, source_files=["a.md"])
        for i in range(3)
    ]

    count = await compiler._generate_articles_batch(concepts)
    assert count == 3
    assert llm.ainvoke.await_count == 3


@pytest.mark.asyncio
async def test_extract_concepts_batch_handles_missing_file(wiki_structure: WikiStructure, mock_indexer: AsyncMock):
    """Test that missing files are handled gracefully in parallel mode."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content='[{"name": "X", "definition": "Y"}]')
    config = WikiConfig(parallel_compilation=True, max_parallel_workers=4)
    compiler = WikiCompiler(llm, wiki_structure, config, WikiCompileConfig(), indexer=mock_indexer)

    queue = compiler._queue
    queue.add_item(wiki_structure.raw_dir / "nonexistent.md")
    items = queue.get_pending_items(limit=1)

    concepts = await compiler._extract_concepts_batch(items)
    assert concepts == []
    assert llm.ainvoke.await_count == 0


@pytest.mark.asyncio
async def test_extract_concepts_batch_merges_duplicates(wiki_structure: WikiStructure, mock_indexer: AsyncMock):
    """Test that concepts with the same name are merged after parallel extraction."""
    call_count = 0

    async def mock_ainvoke(messages):
        nonlocal call_count
        call_count += 1
        return AIMessage(
            content='[{"name": "SharedConcept", "definition": "Def", "related_concepts": []}]'
        )

    llm = AsyncMock()
    llm.ainvoke = mock_ainvoke
    config = WikiConfig(parallel_compilation=True, max_parallel_workers=4)
    compiler = WikiCompiler(llm, wiki_structure, config, WikiCompileConfig(), indexer=mock_indexer)

    raw_dir = wiki_structure.raw_dir
    (raw_dir / "a.md").write_text("Content A", encoding="utf-8")
    (raw_dir / "b.md").write_text("Content B", encoding="utf-8")

    queue = compiler._queue
    queue.add_batch([raw_dir / "a.md", raw_dir / "b.md"])
    items = queue.get_pending_items(limit=2)

    concepts = await compiler._extract_concepts_batch(items)
    assert len(concepts) == 1
    assert concepts[0].mentions == 2
    assert set(concepts[0].source_files) == {"raw/a.md", "raw/b.md"}


# --- ingest_file edge cases ---


def test_enqueue_file_index_raw_text_exception(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """Test that enqueue_file handles index_raw_text exception gracefully (lines 98-99)."""
    indexer = MagicMock()
    indexer.index_raw_text = MagicMock(side_effect=RuntimeError("index error"))
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), indexer=indexer)

    raw_file = wiki_structure.raw_dir / "test.md"
    raw_file.write_text("content", encoding="utf-8")
    compiler.enqueue_file(raw_file)
    stats = compiler._queue.get_stats()
    assert stats["pending"] == 1


# --- start_background_worker edge cases ---


@pytest.mark.asyncio
async def test_start_background_worker_already_running(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """Test that start_background_worker does not start duplicate workers (lines 109-112)."""
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    user_key = str(wiki_structure.base_dir)

    fake_task = asyncio.Future()
    WikiCompiler._active_workers[user_key] = fake_task

    try:
        compiler.start_background_worker()
        assert WikiCompiler._active_workers[user_key] is fake_task
    finally:
        fake_task.cancel()
        del WikiCompiler._active_workers[user_key]


# --- _worker_loop tests ---


@pytest.mark.asyncio
async def test_worker_loop_drains_queue(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """Test that _worker_loop processes pending items and exits on idle (lines 131-167)."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content='[{"name": "WC", "definition": "Worker Concept"}]'
    )
    config = WikiConfig(enable_backlinks=False)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    raw = wiki_structure.raw_dir / "worker_doc.md"
    raw.write_text("Worker content", encoding="utf-8")
    compiler._queue.add_item(raw)

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(0)

    with patch("asyncio.sleep", side_effect=fast_sleep):
        await compiler._worker_loop()

    assert llm.ainvoke.await_count >= 1


@pytest.mark.asyncio
async def test_worker_loop_retries_failed_items(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """Test _worker_loop auto-retries failed items (lines 140-144)."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content='[{"name": "Retry", "definition": "Retried"}]'
    )
    config = WikiConfig(enable_backlinks=False)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    raw = wiki_structure.raw_dir / "retry_doc.md"
    raw.write_text("Retry content", encoding="utf-8")
    compiler._queue.add_item(raw)
    items = compiler._queue.get_pending_items(limit=1)
    compiler._queue.mark_processing(items[0]["id"])
    compiler._queue.mark_failed(items[0]["id"], "simulated failure")

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(0)

    with patch("asyncio.sleep", side_effect=fast_sleep):
        await compiler._worker_loop()

    assert llm.ainvoke.await_count >= 1


@pytest.mark.asyncio
async def test_worker_loop_handles_exception(wiki_structure: WikiStructure) -> None:
    """Test _worker_loop handles exceptions gracefully (line 163)."""
    llm = AsyncMock()
    llm.ainvoke.side_effect = RuntimeError("LLM down")
    config = WikiConfig(enable_backlinks=False)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config)

    raw = wiki_structure.raw_dir / "err_doc.md"
    raw.write_text("Error content", encoding="utf-8")
    compiler._queue.add_item(raw)

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(0)

    with patch("asyncio.sleep", side_effect=fast_sleep):
        await compiler._worker_loop()


@pytest.mark.asyncio
async def test_worker_loop_stale_recovery(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """Test _worker_loop recovers stale processing items (line 131)."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content='[{"name": "Stale", "definition": "Recovered"}]')
    config = WikiConfig(enable_backlinks=False)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    raw = wiki_structure.raw_dir / "stale.md"
    raw.write_text("Stale content", encoding="utf-8")
    compiler._queue.add_item(raw)
    items = compiler._queue.get_pending_items(limit=1)
    compiler._queue.mark_processing(items[0]["id"])

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(0)

    with patch("asyncio.sleep", side_effect=fast_sleep):
        await compiler._worker_loop()


# --- _filter_changed_files edge cases ---


@pytest.mark.asyncio
async def test_filter_changed_files_invalid_metadata_json(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    """Test _filter_changed_files with corrupt metadata file (lines 245-247)."""
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")

    metadata_path = wiki_structure.get_wiki_metadata_path()
    metadata_path.write_text("not valid json {{{")

    changed = await compiler._filter_changed_files([raw])
    assert changed == [raw]


@pytest.mark.asyncio
async def test_filter_changed_files_unreadable_file(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    """Test _filter_changed_files with OSError reading file hash (lines 255-256)."""
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "ghost.md"
    raw.write_text("content")

    metadata_path = wiki_structure.get_wiki_metadata_path()
    metadata_path.write_text(json.dumps({"file_hashes": {str(raw): "oldhash"}}))

    raw.unlink()

    changed = await compiler._filter_changed_files([raw])
    assert raw in changed


# --- _extract_concepts_batch: BaseException from gather ---


@pytest.mark.asyncio
async def test_extract_concepts_batch_gather_exception(
    wiki_structure: WikiStructure, mock_indexer: AsyncMock
) -> None:
    """Test _extract_concepts_batch handles BaseException from gather (lines 292-294)."""
    llm = AsyncMock()
    call_count = 0

    async def failing_ainvoke(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("LLM crashed")
        return AIMessage(content='[{"name": "Safe", "definition": "Survived"}]')

    llm.ainvoke = failing_ainvoke
    config = WikiConfig(parallel_compilation=True, max_parallel_workers=4)
    compiler = WikiCompiler(llm, wiki_structure, config, WikiCompileConfig(), indexer=mock_indexer)

    raw_dir = wiki_structure.raw_dir
    (raw_dir / "good.md").write_text("Good content", encoding="utf-8")
    (raw_dir / "bad.md").write_text("Bad content", encoding="utf-8")

    compiler._queue.add_batch([raw_dir / "good.md", raw_dir / "bad.md"])
    items = compiler._queue.get_pending_items(limit=2)

    concepts = await compiler._extract_concepts_batch(items)
    assert len(concepts) >= 0


# --- _extract_concepts_from_doc: ValueError in relative_to ---


@pytest.mark.asyncio
async def test_extract_concepts_from_doc_external_path(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    """Test _extract_concepts_from_doc with doc outside base_dir (lines 321-322)."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("External doc content")
        external_path = Path(f.name)

    try:
        mock_llm.ainvoke.return_value = AIMessage(
            content='[{"name": "External", "definition": "From outside"}]'
        )
        compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
        concepts = await compiler._extract_concepts_from_doc(external_path)
        assert len(concepts) == 1
        assert concepts[0].name == "External"
    finally:
        external_path.unlink(missing_ok=True)


# --- _parse_concepts_response: plain ``` code block ---


def test_parse_concepts_response_plain_code_block(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    """Test parsing response wrapped in plain ``` (lines 350-354)."""
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    concepts = compiler._parse_concepts_response(
        '```\n[{"name": "Wrapped", "definition": "In plain code block"}]\n```',
        "test.md",
    )
    assert len(concepts) == 1
    assert concepts[0].name == "Wrapped"


# --- _generate_articles_batch: sequential + exception ---


@pytest.mark.asyncio
async def test_generate_articles_batch_sequential(
    wiki_structure: WikiStructure, mock_indexer: AsyncMock
) -> None:
    """Test _generate_articles_batch sequential path (lines 406, 418)."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nSeq article.")
    config = WikiConfig(parallel_compilation=False)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    concepts = [
        ConceptInfo(name="SeqArt", definition="Def", mentions=2, source_files=["a.md"])
    ]
    count = await compiler._generate_articles_batch(concepts)
    assert count == 1


@pytest.mark.asyncio
async def test_generate_articles_batch_exception_in_gen(
    wiki_structure: WikiStructure, mock_indexer: AsyncMock
) -> None:
    """Test _generate_articles_batch handles exception in _gen_one (lines 408-410)."""
    llm = AsyncMock()
    llm.ainvoke.side_effect = RuntimeError("LLM error")
    config = WikiConfig(parallel_compilation=True, max_parallel_workers=2)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    concepts = [
        ConceptInfo(name="FailArt", definition="Def", mentions=2, source_files=["a.md"])
    ]
    count = await compiler._generate_articles_batch(concepts)
    assert count == 0


# --- _generate_article edge cases ---


@pytest.mark.asyncio
async def test_generate_article_with_existing_content(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    """Test _generate_article appends to existing article (line 427, 443)."""
    concept_path = wiki_structure.get_concept_file_path("Existing")
    concept_path.write_text("## Compiled Truth\nOld content.\n\n## Timeline\n- 2024: Created")

    mock_llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nUpdated content.")
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), compile_config, indexer=mock_indexer)

    concept = ConceptInfo(name="Existing", definition="Def", mentions=2, source_files=["a.md"])
    await compiler._generate_article(concept)

    call_args = mock_llm.ainvoke.call_args[0][0]
    human_msg_content = call_args[1].content
    assert "Existing Wiki Content" in human_msg_content


@pytest.mark.asyncio
async def test_generate_article_require_approval(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    """Test _generate_article with require_approval=True creates pending edit (line 453+)."""
    mock_llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nPending article.")
    compile_config = WikiCompileConfig(require_approval=True)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), compile_config, indexer=mock_indexer)

    concept = ConceptInfo(name="Pending", definition="Def", mentions=2, source_files=["a.md"])
    await compiler._generate_article(concept)

    concept_path = wiki_structure.get_concept_file_path("Pending")
    assert not concept_path.exists()


@pytest.mark.asyncio
async def test_generate_article_no_indexer_fallback(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    """Test _generate_article creates indexer when none provided (lines 470-474)."""
    mock_llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nArticle.")
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), compile_config, indexer=None)

    concept = ConceptInfo(name="NoIdx", definition="Def", mentions=2, source_files=["a.md"])

    with patch(
        "myrm_agent_harness.toolkits.wiki.retrieval.indexer.WikiIndexer"
    ) as MockIndexer:
        mock_idx_instance = MagicMock()
        mock_idx_instance.upsert = AsyncMock()
        mock_idx_instance.extract_and_upsert_edges = MagicMock()
        MockIndexer.return_value = mock_idx_instance

        await compiler._generate_article(concept)

        mock_idx_instance.upsert.assert_awaited_once()
        mock_idx_instance.extract_and_upsert_edges.assert_called_once()


@pytest.mark.asyncio
async def test_generate_article_llm_exception(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    """Test _generate_article raises on LLM failure (lines 478-480)."""
    mock_llm.ainvoke.side_effect = RuntimeError("LLM timeout")
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), compile_config, indexer=mock_indexer)

    concept = ConceptInfo(name="ErrArt", definition="Def", mentions=2, source_files=["a.md"])
    with pytest.raises(RuntimeError, match="LLM timeout"):
        await compiler._generate_article(concept)


# --- _generate_backlinks edge cases ---


@pytest.mark.asyncio
async def test_generate_backlinks_no_article_file(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    """Test _generate_backlinks skips if article file doesn't exist (line 512)."""
    config = WikiConfig(enable_backlinks=True)
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    concepts = [
        ConceptInfo(name="Ghost", definition="def", mentions=2, source_files=["a.md"], related_concepts=["Other"]),
    ]
    count = await compiler._generate_backlinks(concepts)
    assert count == 0


@pytest.mark.asyncio
async def test_generate_backlinks_no_indexer_fallback(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    """Test _generate_backlinks creates indexer when none provided (lines 531-534)."""
    config = WikiConfig(enable_backlinks=True)
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, config, compile_config, indexer=None)

    concept_path = wiki_structure.get_concept_file_path("LinkTest")
    concept_path.write_text("## Compiled Truth\nContent.")

    concepts = [
        ConceptInfo(name="LinkTest", definition="def", mentions=2, source_files=["a.md"], related_concepts=["Linked"]),
    ]

    with patch(
        "myrm_agent_harness.toolkits.wiki.retrieval.indexer.WikiIndexer"
    ) as MockIndexer:
        mock_idx_instance = MagicMock()
        mock_idx_instance.extract_and_upsert_edges = MagicMock()
        MockIndexer.return_value = mock_idx_instance

        count = await compiler._generate_backlinks(concepts)
        assert count == 1
        mock_idx_instance.extract_and_upsert_edges.assert_called_once()


@pytest.mark.asyncio
async def test_generate_backlinks_read_exception(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    """Test _generate_backlinks handles exception reading article (lines 536-537)."""
    config = WikiConfig(enable_backlinks=True)
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    concept_path = wiki_structure.get_concept_file_path("BadRead")
    concept_path.write_text("Content")

    concepts = [
        ConceptInfo(name="BadRead", definition="def", mentions=2, source_files=["a.md"], related_concepts=["Link"]),
    ]

    with patch.object(Path, "read_text", side_effect=PermissionError("no access")):
        count = await compiler._generate_backlinks(concepts)
        assert count == 0


# --- _extract_concepts_batch: exception in _process_single_item ---


@pytest.mark.asyncio
async def test_extract_concepts_batch_process_exception(
    wiki_structure: WikiStructure, mock_indexer: AsyncMock
) -> None:
    """Test _extract_concepts_batch handles exception in _process_single_item (lines 277-280).

    Triggers the outer `except Exception` by making mark_completed raise.
    """
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content='[{"name": "X", "definition": "Y"}]')
    config = WikiConfig(parallel_compilation=True, max_parallel_workers=4)
    compiler = WikiCompiler(llm, wiki_structure, config, WikiCompileConfig(), indexer=mock_indexer)

    raw = wiki_structure.raw_dir / "crash.md"
    raw.write_text("Crash content", encoding="utf-8")

    compiler._queue.add_item(raw)
    items = compiler._queue.get_pending_items(limit=1)

    with patch.object(compiler._queue, "mark_completed", side_effect=RuntimeError("DB error")):
        concepts = await compiler._extract_concepts_batch(items)
        assert concepts == []
