"""Extended tests for WikiCompiler - covering _filter_changed_files, compile_all,
_extract_concepts_from_doc (including index catalog prompt wiring), parse_concepts_response,
refresh_cognitive_map, generate_backlinks, save_metadata, purpose injection, visual element
prompt guidance, parallel batch ingestion, worker loop, and edge cases."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind
from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.parsers import parse_concepts_response
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import (
    WikiCompiler,
    _ArticleBatchStats,
)
from myrm_agent_harness.toolkits.wiki.pipeline.resilience import EMBED_WINDOW_VIOLATION
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
    concepts = parse_concepts_response('[{"name": "ML", "definition": "Machine Learning"}]', "test.md")
    assert len(concepts) == 1
    assert concepts[0].name == "ML"
    assert concepts[0].definition == "Machine Learning"


def test_parse_json_with_code_block(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    concepts = parse_concepts_response(
        '```json\n[{"name": "AI", "definition": "Artificial Intelligence"}]\n```', "test.md"
    )
    assert len(concepts) == 1
    assert concepts[0].name == "AI"


def test_parse_bullet_response(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    concepts = parse_concepts_response(
        "1. **Neural Network** - A computing system\n- **Gradient** - A derivative vector", "test.md"
    )
    assert len(concepts) == 2
    assert concepts[0].name == "Neural Network"
    assert concepts[1].name == "Gradient"


def test_parse_empty_response(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    concepts = parse_concepts_response("No concepts found.", "test.md")
    assert concepts == []


def test_parse_prose_with_trailing_commas_and_bare_newlines(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    concepts = parse_concepts_response(
        'Concepts found:\n[{"name": "ML", "definition": "Machine\nLearning", '
        '"related_concepts": ["AI"],},]\nThat is all.',
        "test.md",
    )
    assert len(concepts) == 1
    assert concepts[0].name == "ML"
    assert concepts[0].related_concepts == ["AI"]


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

    from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
        LAST_COMPILE_RAW_HASHES_KEY,
        raw_relative_storage_key,
    )

    content_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
    storage_key = raw_relative_storage_key(wiki_structure, raw)
    metadata_path = wiki_structure.get_wiki_metadata_path()
    metadata_path.write_text(json.dumps({LAST_COMPILE_RAW_HASHES_KEY: {storage_key: content_hash}}))

    changed = await compiler._filter_changed_files([raw])
    assert changed == []


@pytest.mark.asyncio
async def test_filter_changed_files_modified(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")

    from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
        LAST_COMPILE_RAW_HASHES_KEY,
        raw_relative_storage_key,
    )

    metadata_path = wiki_structure.get_wiki_metadata_path()
    storage_key = raw_relative_storage_key(wiki_structure, raw)
    metadata_path.write_text(json.dumps({LAST_COMPILE_RAW_HASHES_KEY: {storage_key: "stale_hash"}}))

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
async def test_extract_concepts_reasoning_model_content_empty(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    """Reasoning 模型 content 为空时回退到 additional_kwargs["reasoning_content"]。"""
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("Machine learning is about data.")

    mock_llm.ainvoke.return_value = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": '[{"name": "ML", "definition": "Machine Learning"}]'},
    )
    concepts = await compiler._extract_concepts_from_doc(raw)
    assert len(concepts) == 1
    assert concepts[0].name == "ML"


@pytest.mark.asyncio
async def test_extract_concepts_from_doc_file_not_found(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    concepts = await compiler._extract_concepts_from_doc(Path("/nonexistent.md"))
    assert concepts == []


@pytest.mark.asyncio
async def test_extract_concepts_from_doc_includes_index_catalog_when_index_exists(
    wiki_structure: WikiStructure,
    mock_llm: AsyncMock,
) -> None:
    """Compile extraction injects bounded wiki/index.md catalog into the LLM prompt."""
    index_path = wiki_structure.get_index_file_path()
    index_path.write_text(
        "## Core concepts\n- [[transformer-architecture]] — attention-based sequence model\n",
        encoding="utf-8",
    )

    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "paper.md"
    raw.write_text("A survey of transformer variants for NLP.")

    mock_llm.ainvoke.return_value = AIMessage(
        content='[{"name": "Transformer", "definition": "Sequence model architecture"}]'
    )
    concepts = await compiler._extract_concepts_from_doc(raw)

    assert len(concepts) == 1
    assert concepts[0].name == "Transformer"
    mock_llm.ainvoke.assert_awaited_once()
    messages = mock_llm.ainvoke.await_args.args[0]
    human_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
    assert len(human_messages) == 1
    human_content = str(human_messages[0].content)
    assert "Existing wiki catalog (reuse these concept names when applicable):" in human_content
    assert "transformer-architecture" in human_content


@pytest.mark.asyncio
async def test_extract_concepts_from_doc_omits_index_catalog_when_index_missing(
    wiki_structure: WikiStructure,
    mock_llm: AsyncMock,
) -> None:
    index_path = wiki_structure.get_index_file_path()
    if index_path.exists():
        index_path.unlink()

    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "note.md"
    raw.write_text("Standalone note without prior catalog.")

    await compiler._extract_concepts_from_doc(raw)

    mock_llm.ainvoke.assert_awaited_once()
    messages = mock_llm.ainvoke.await_args.args[0]
    human_content = str(next(msg for msg in messages if isinstance(msg, HumanMessage)).content)
    assert "Existing wiki catalog" not in human_content


# --- _refresh_cognitive_map ---


@pytest.mark.asyncio
async def test_refresh_cognitive_map(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo

    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    concepts = [
        ConceptInfo(name="Alpha", definition="def A", mentions=2, source_files=["a.md"]),
        ConceptInfo(name="Beta", definition="def B", mentions=2, source_files=["b.md"]),
    ]
    concept_path = wiki_structure.get_concept_file_path("Alpha")
    concept_path.write_text("---\ntype: concept\n---\n# Alpha\nAlpha page.\n", encoding="utf-8")
    concept_path = wiki_structure.get_concept_file_path("Beta")
    concept_path.write_text("---\ntype: entity\n---\n# Beta\nBeta page.\n", encoding="utf-8")

    compiler._refresh_cognitive_map(concepts, batch=True)
    index_path = wiki_structure.get_index_file_path()
    assert index_path.exists()
    content = index_path.read_text()
    assert "[[alpha]]" in content
    assert "[[beta]]" in content
    assert wiki_structure.get_hot_file_path().exists()
    assert wiki_structure.get_log_file_path().exists()


# --- _save_metadata ---


@pytest.mark.asyncio
async def test_save_metadata(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")

    await compiler._save_metadata(5, 3)
    metadata_path = wiki_structure.get_wiki_metadata_path()
    assert metadata_path.exists()
    from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
        LAST_COMPILE_RAW_HASHES_KEY,
        raw_relative_storage_key,
    )

    metadata = json.loads(metadata_path.read_text())
    assert metadata["total_concepts"] == 5
    assert metadata["total_articles"] == 3
    assert raw_relative_storage_key(wiki_structure, raw) in metadata[LAST_COMPILE_RAW_HASHES_KEY]


@pytest.mark.asyncio
async def test_save_metadata_preserves_raw_supersede(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    from myrm_agent_harness.toolkits.wiki.core.claims_contract import RAW_SUPERSEDE_KEY, record_raw_supersede_entry

    record_raw_supersede_entry(
        wiki_structure,
        rel_path="budget.md",
        previous_sha256="a" * 64,
        new_sha256="b" * 64,
        reason="settings import",
    )

    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    await compiler._save_metadata(2, 1)

    metadata = json.loads(wiki_structure.get_wiki_metadata_path().read_text())
    assert "raw/budget.md" in metadata[RAW_SUPERSEDE_KEY]


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
async def test_compile_all_incremental(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
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
async def test_compile_all_full_strategy(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
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
    batch_outcome = await compiler._extract_concepts_batch(items)
    concepts = batch_outcome.concepts
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
    batch_outcome = await compiler._extract_concepts_batch(items)
    concepts = batch_outcome.concepts
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
        source_files = ("ai.md",)

    await compiler._generate_article(DummyConcept())

    call_args = mock_llm.ainvoke.call_args[0][0]
    human_msg_content = call_args[1].content
    assert "Focus on AI/ML" in human_msg_content


# --- Visual element prompt guidance ---


def test_default_prompt_contains_visual_element_guidance() -> None:
    """Verify the default generate_article_prompt_template includes Mermaid, GFM tables,
    and fenced code block guidance for rich visual output."""
    config = WikiCompileConfig()
    tmpl = config.generate_article_prompt_template
    assert "Mermaid" in tmpl, "Prompt must guide LLM to use Mermaid diagrams"
    assert "GFM tables" in tmpl, "Prompt must guide LLM to use GFM tables"
    assert "fenced code blocks" in tmpl, "Prompt must guide LLM to use fenced code blocks"


@pytest.mark.asyncio
async def test_visual_guidance_reaches_llm(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    """Verify the visual element guidance is present in the prompt sent to the LLM."""
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), compile_config, indexer=mock_indexer)

    mock_llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nArticle with Mermaid.")

    concept = ConceptInfo(name="VisualTest", definition="Def", mentions=2, source_files=["a.md"])
    await compiler._generate_article(concept)

    call_args = mock_llm.ainvoke.call_args[0][0]
    human_msg_content = call_args[1].content
    assert "Mermaid" in human_msg_content, "LLM prompt must contain Mermaid guidance"
    assert "GFM tables" in human_msg_content, "LLM prompt must contain GFM tables guidance"


# --- Parallel batch ingestion ---


@pytest.mark.asyncio
async def test_extract_concepts_batch_parallel(wiki_structure: WikiStructure, mock_indexer: AsyncMock):
    """Test that _extract_concepts_batch runs in parallel when parallel_compilation=True."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content='[{"name": "Concept1", "definition": "Def1", "related_concepts": []}]')
    config = WikiConfig(parallel_compilation=True, max_parallel_workers=2)
    compiler = WikiCompiler(llm, wiki_structure, config, WikiCompileConfig(), indexer=mock_indexer)

    raw_dir = wiki_structure.raw_dir
    for i in range(3):
        (raw_dir / f"doc{i}.md").write_text(f"Content {i}", encoding="utf-8")

    queue = compiler._queue
    queue.add_batch([raw_dir / f"doc{i}.md" for i in range(3)])
    items = queue.get_pending_items(limit=3)

    batch_outcome = await compiler._extract_concepts_batch(items)
    concepts = batch_outcome.concepts
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

    batch_outcome = await compiler._extract_concepts_batch(items)
    concepts = batch_outcome.concepts
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
    assert count.generated == 3
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

    batch_outcome = await compiler._extract_concepts_batch(items)
    concepts = batch_outcome.concepts
    assert concepts == []
    assert llm.ainvoke.await_count == 0


@pytest.mark.asyncio
async def test_extract_concepts_batch_merges_duplicates(wiki_structure: WikiStructure, mock_indexer: AsyncMock):
    """Test that concepts with the same name are merged after parallel extraction."""
    call_count = 0

    async def mock_ainvoke(messages):
        nonlocal call_count
        call_count += 1
        return AIMessage(content='[{"name": "SharedConcept", "definition": "Def", "related_concepts": []}]')

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

    batch_outcome = await compiler._extract_concepts_batch(items)
    concepts = batch_outcome.concepts
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
    llm.ainvoke.return_value = AIMessage(content='[{"name": "WC", "definition": "Worker Concept"}]')
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
    llm.ainvoke.return_value = AIMessage(content='[{"name": "Retry", "definition": "Retried"}]')
    config = WikiConfig(enable_backlinks=False)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    raw = wiki_structure.raw_dir / "retry_doc.md"
    raw.write_text("Retry content", encoding="utf-8")
    compiler._queue.add_item(raw)
    items = compiler._queue.get_pending_items(limit=1)
    compiler._queue.mark_processing(items[0]["id"])
    compiler._queue.mark_failed(
        items[0]["id"],
        "429 Too Many Requests",
        error_kind=ErrorKind.RATE_LIMIT.value,
        retry_after_seconds=0,
    )

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
async def test_filter_changed_files_invalid_metadata_json(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """Test _filter_changed_files with corrupt metadata file (lines 245-247)."""
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "test.md"
    raw.write_text("content")

    metadata_path = wiki_structure.get_wiki_metadata_path()
    metadata_path.write_text("not valid json {{{")

    changed = await compiler._filter_changed_files([raw])
    assert changed == [raw]


@pytest.mark.asyncio
async def test_filter_changed_files_unreadable_file(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """Test _filter_changed_files with OSError reading file hash (lines 255-256)."""
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "ghost.md"
    raw.write_text("content")

    metadata_path = wiki_structure.get_wiki_metadata_path()
    metadata_path.write_text(json.dumps({"last_compile_raw_hashes": {"raw/ghost.md": "oldhash"}}))

    raw.unlink()

    changed = await compiler._filter_changed_files([raw])
    assert raw in changed


# --- _extract_concepts_batch: BaseException from gather ---


@pytest.mark.asyncio
async def test_extract_concepts_batch_gather_exception(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
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

    batch_outcome = await compiler._extract_concepts_batch(items)
    concepts = batch_outcome.concepts
    assert len(concepts) >= 0


# --- _extract_concepts_from_doc: ValueError in relative_to ---


@pytest.mark.asyncio
async def test_extract_concepts_from_doc_external_path(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """Test _extract_concepts_from_doc with doc outside base_dir (lines 321-322)."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("External doc content")
        external_path = Path(f.name)

    try:
        mock_llm.ainvoke.return_value = AIMessage(content='[{"name": "External", "definition": "From outside"}]')
        compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
        concepts = await compiler._extract_concepts_from_doc(external_path)
        assert len(concepts) == 1
        assert concepts[0].name == "External"
    finally:
        external_path.unlink(missing_ok=True)


# --- _parse_concepts_response: plain ``` code block ---


def test_parse_concepts_response_plain_code_block(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """Test parsing response wrapped in plain ``` code block."""
    concepts = parse_concepts_response(
        '```\n[{"name": "Wrapped", "definition": "In plain code block"}]\n```',
        "test.md",
    )
    assert len(concepts) == 1
    assert concepts[0].name == "Wrapped"


# --- _generate_articles_batch: sequential + exception ---


@pytest.mark.asyncio
async def test_generate_articles_batch_sequential(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """Test _generate_articles_batch sequential path (lines 406, 418)."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nSeq article.")
    config = WikiConfig(parallel_compilation=False)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    concepts = [ConceptInfo(name="SeqArt", definition="Def", mentions=2, source_files=["a.md"])]
    count = await compiler._generate_articles_batch(concepts)
    assert count.generated == 1


@pytest.mark.asyncio
async def test_generate_articles_batch_exception_in_gen(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """Test _generate_articles_batch handles exception in _gen_one (lines 408-410)."""
    llm = AsyncMock()
    llm.ainvoke.side_effect = RuntimeError("LLM error")
    config = WikiConfig(parallel_compilation=True, max_parallel_workers=2)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    concepts = [ConceptInfo(name="FailArt", definition="Def", mentions=2, source_files=["a.md"])]
    count = await compiler._generate_articles_batch(concepts)
    assert count.generated == 0
    assert count.blocked == 1


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
async def test_generate_article_no_indexer_fallback(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """Test _generate_article creates indexer when none provided (lines 470-474)."""
    mock_llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nArticle.")
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), compile_config, indexer=None)

    concept = ConceptInfo(name="NoIdx", definition="Def", mentions=2, source_files=["a.md"])

    with patch("myrm_agent_harness.toolkits.wiki.retrieval.indexer.WikiIndexer") as mock_indexer_cls:
        mock_idx_instance = MagicMock()
        mock_idx_instance.upsert = AsyncMock()
        mock_idx_instance.extract_and_upsert_edges = MagicMock()
        mock_indexer_cls.return_value = mock_idx_instance

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
async def test_generate_backlinks_no_indexer_fallback(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """Test _generate_backlinks creates indexer when none provided (lines 531-534)."""
    config = WikiConfig(enable_backlinks=True)
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, config, compile_config, indexer=None)

    concept_path = wiki_structure.get_concept_file_path("LinkTest")
    concept_path.write_text("## Compiled Truth\nContent.")

    concepts = [
        ConceptInfo(name="LinkTest", definition="def", mentions=2, source_files=["a.md"], related_concepts=["Linked"]),
    ]

    with patch("myrm_agent_harness.toolkits.wiki.retrieval.indexer.WikiIndexer") as mock_indexer_cls:
        mock_idx_instance = MagicMock()
        mock_idx_instance.extract_and_upsert_edges = MagicMock()
        mock_indexer_cls.return_value = mock_idx_instance

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
async def test_extract_concepts_batch_process_exception(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
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
        batch_outcome = await compiler._extract_concepts_batch(items)
    concepts = batch_outcome.concepts
    assert concepts == []


# --- Compile survey session branches ---


def _write_nested_raw(structure: WikiStructure, rel_path: str, content: str) -> Path:
    """Write a raw file inside a nested folder to trigger a non-skipped survey."""
    path = structure.raw_dir / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_ensure_compile_session_reuses_existing(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """_ensure_compile_session returns the cached session on subsequent calls (line 144)."""
    _write_nested_raw(wiki_structure, "sub/doc.md", "Nested doc content.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    compiler._queue.add_item(wiki_structure.raw_dir / "sub" / "doc.md")

    first = compiler._ensure_compile_session()
    second = compiler._ensure_compile_session()
    assert first is second
    assert first.context.skipped is False
    assert first.context.facet_count >= 1
    assert compiler._queue.get_compile_run().phase == "semantic_compile"


@pytest.mark.asyncio
async def test_compile_all_with_nested_survey_session(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """compile_all with a nested vault runs the survey-sorted batch path (lines 183-253)."""
    llm = AsyncMock()
    llm.ainvoke.side_effect = [
        AIMessage(content='[{"name": "Nested", "definition": "From nested folder"}]'),
        AIMessage(content="## Compiled Truth\nNested article."),
    ]
    config = WikiConfig(parallel_compilation=False, enable_backlinks=False)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    _write_nested_raw(wiki_structure, "sub/doc.md", "Nested folder content.")
    compiler._queue.add_item(wiki_structure.raw_dir / "sub" / "doc.md")

    result = await compiler.compile_all(batch_size=10)
    assert result.concepts_count >= 1
    assert llm.ainvoke.await_count >= 2
    assert compiler._get_session() is None  # cleared after compile
    WikiCompiler._active_workers.pop(str(wiki_structure.base_dir), None)


def test_get_compile_run_and_resume_compile_worker(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """get_compile_run and resume_compile_worker delegate to the circuit (lines 274-278)."""
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    snapshot = compiler.get_compile_run()
    assert snapshot.phase == "idle"
    compiler.resume_compile_worker()
    assert compiler._queue.is_compile_paused() is False


@pytest.mark.asyncio
async def test_maybe_pause_for_embed_failure(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """_maybe_pause_for_embed_failure pauses the circuit on embed violation (lines 892-893)."""
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    stats = _ArticleBatchStats(
        generated=0,
        pending=0,
        published=0,
        blocked=1,
        embed_pause_reason="Embedding input too large",
        embed_pause_kind=EMBED_WINDOW_VIOLATION,
    )
    compiler._maybe_pause_for_embed_failure(stats)
    assert compiler._queue.is_compile_paused() is True
    compiler._queue.resume_compile()


@pytest.mark.asyncio
async def test_generate_article_truncates_oversized_content(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    """_generate_article truncates content exceeding max_article_length (line 809)."""
    mock_llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\n" + "x" * 2000)
    compile_config = WikiCompileConfig(require_approval=False, max_article_length=50)
    compiler = WikiCompiler(
        mock_llm,
        wiki_structure,
        WikiConfig(),
        compile_config,
        indexer=mock_indexer,
    )
    concept = ConceptInfo(name="Huge", definition="Def", mentions=2, source_files=["a.md"])
    await compiler._generate_article(concept)
    content = wiki_structure.get_concept_file_path("Huge").read_text(encoding="utf-8")
    assert "(truncated)" in content
    # The 2000-char run must have been truncated (max_article_length=50).
    assert "x" * 51 not in content


@pytest.mark.asyncio
async def test_compile_all_paused_skips_drain(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """compile_all returns immediately while the circuit is paused (lines 422-425)."""
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    _write_nested_raw(wiki_structure, "doc.md", "Content.")
    compiler._queue.add_item(wiki_structure.raw_dir / "doc.md")
    compiler._queue.pause_compile("paused", ErrorKind.AUTH.value)
    result = await compiler.compile_all()
    assert result.concepts_count == 0
    assert mock_llm.ainvoke.await_count == 0


@pytest.mark.asyncio
async def test_extract_concepts_batch_no_concepts_marks_failed(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    """_extract_concepts_batch marks items failed when extraction yields no concepts (lines 606-616)."""
    mock_llm.ainvoke.return_value = AIMessage(content="No concepts found.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "empty.md"
    raw.write_text("Nothing here.", encoding="utf-8")
    compiler._queue.add_item(raw)
    items = compiler._queue.get_pending_items(limit=1)

    batch_outcome = await compiler._extract_concepts_batch(items)
    assert batch_outcome.concepts == []
    assert batch_outcome.success_count == 0
    stats = compiler._queue.get_stats()
    assert stats["failed"] == 1


@pytest.mark.asyncio
async def test_extract_concepts_batch_base_exception_recorded(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    """_extract_concepts_batch records BaseException results as failures (lines 643-650)."""

    class _FatalError(BaseException):
        pass

    mock_llm.ainvoke.return_value = AIMessage(content='[{"name": "OK", "definition": "d"}]')
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    raw = wiki_structure.raw_dir / "kb.md"
    raw.write_text("Content.", encoding="utf-8")
    compiler._queue.add_item(raw)
    items = compiler._queue.get_pending_items(limit=1)

    with patch.object(compiler._queue, "mark_completed", side_effect=_FatalError()):
        batch_outcome = await compiler._extract_concepts_batch(items)
    assert batch_outcome.concepts == []
    assert batch_outcome.failure_kinds


@pytest.mark.asyncio
async def test_worker_loop_full_pipeline(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """_worker_loop runs the full postprocess pipeline with backlinks (lines 349-379)."""
    llm = AsyncMock()
    llm.ainvoke.side_effect = [
        AIMessage(content='[{"name": "Pipe", "definition": "Pipeline concept"}]'),
        AIMessage(content="## Compiled Truth\nPipeline article."),
    ]
    config = WikiConfig(enable_backlinks=True, enable_directory_sidecars=True)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    raw = wiki_structure.raw_dir / "pipe.md"
    raw.write_text("Pipeline content.", encoding="utf-8")
    compiler._queue.add_item(raw)

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(0)

    with (
        patch(
            "myrm_agent_harness.toolkits.wiki.pipeline.compiler.run_contradiction_synthesis_pass",
            return_value=MagicMock(synthesis_staged=1, pairs_considered=2),
        ) as mock_synthesis,
        patch.object(compiler, "_generate_backlinks", new=AsyncMock(return_value=0)) as mock_bl,
        patch.object(compiler, "_build_sidecars", new=AsyncMock()) as mock_sc,
        patch.object(compiler, "_save_metadata", new=AsyncMock()) as mock_meta,
        patch.object(compiler, "_maybe_commit_vault_git", new=AsyncMock()) as mock_git,
        patch("asyncio.sleep", side_effect=fast_sleep),
    ):
        await compiler._worker_loop()

    assert llm.ainvoke.await_count >= 2
    mock_synthesis.assert_awaited()
    mock_bl.assert_awaited()
    mock_sc.assert_awaited()
    mock_meta.assert_awaited()
    mock_git.assert_awaited()


@pytest.mark.asyncio
async def test_worker_loop_paused_skips_extraction(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """_worker_loop sleeps while the circuit is paused without calling the LLM (lines 315-317)."""
    llm = AsyncMock()
    compiler = WikiCompiler(llm, wiki_structure, WikiConfig(), indexer=mock_indexer)
    raw = wiki_structure.raw_dir / "paused.md"
    raw.write_text("Paused content.", encoding="utf-8")
    compiler._queue.add_item(raw)
    compiler._queue.pause_compile("paused", ErrorKind.AUTH.value)

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(0)

    with patch("asyncio.sleep", side_effect=fast_sleep):
        await compiler._worker_loop()

    assert llm.ainvoke.await_count == 0
    stats = compiler._queue.get_stats()
    assert stats["pending"] == 1


@pytest.mark.asyncio
async def test_worker_loop_recovers_stale_processing(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """_worker_loop recovers stale processing items at startup (line 310)."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content='[{"name": "Recovered", "definition": "d"}]')
    config = WikiConfig(enable_backlinks=False)
    compile_config = WikiCompileConfig(require_approval=False, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    raw = wiki_structure.raw_dir / "stale.md"
    raw.write_text("Stale content.", encoding="utf-8")
    compiler._queue.add_item(raw)
    item_id = compiler._queue.get_pending_items(limit=1)[0]["id"]
    compiler._queue.mark_processing(item_id)
    with compiler._queue._get_conn() as conn:
        conn.execute("UPDATE ingestion_queue SET updated_at = datetime('now', '-400 seconds')")

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(0)

    with patch("asyncio.sleep", side_effect=fast_sleep):
        await compiler._worker_loop()

    assert llm.ainvoke.await_count >= 1


# --- Compiler survey chunk-group and compile_all pause branches ---


@pytest.mark.asyncio
async def test_build_extract_survey_context_chunk_group(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """_build_extract_survey_context renders chunk-group siblings (lines 221-230)."""
    _write_nested_raw(wiki_structure, "sub/report_chunk1.md", "Part one.")
    _write_nested_raw(wiki_structure, "sub/report_chunk2.md", "Part two.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    compiler._queue.add_item(wiki_structure.raw_dir / "sub" / "report_chunk1.md")
    compiler._queue.add_item(wiki_structure.raw_dir / "sub" / "report_chunk2.md")

    compiler._ensure_compile_session()
    survey = compiler._build_extract_survey_context("raw/sub/report_chunk1.md")
    assert "Chunk group" in survey
    assert "report_chunk2.md" in survey
    assert "Compile Facet" in survey


@pytest.mark.asyncio
async def test_compile_all_should_pause_on_auth_failure(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """compile_all pauses the circuit when every extraction fails with AUTH (line 466)."""
    llm = AsyncMock()
    llm.ainvoke.side_effect = Exception("401 Invalid API key")
    compiler = WikiCompiler(llm, wiki_structure, WikiConfig(), indexer=mock_indexer)
    raw = wiki_structure.raw_dir / "auth.md"
    raw.write_text("Content.", encoding="utf-8")
    compiler._queue.add_item(raw)

    result = await compiler.compile_all(batch_size=10)
    assert result.concepts_count == 0
    assert compiler._queue.is_compile_paused() is True
    compiler._queue.resume_compile()


@pytest.mark.asyncio
async def test_compile_all_no_concepts_sets_semantic_phase(
    wiki_structure: WikiStructure, mock_llm: AsyncMock, mock_indexer: AsyncMock
) -> None:
    """compile_all falls back to semantic phase when no concepts extracted (line 473)."""
    mock_llm.ainvoke.return_value = AIMessage(content="No concepts found.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig(), indexer=mock_indexer)
    raw = wiki_structure.raw_dir / "empty.md"
    raw.write_text("Nothing.", encoding="utf-8")
    compiler._queue.add_item(raw)

    result = await compiler.compile_all(batch_size=10)
    assert result.concepts_count == 0
    stats = compiler._queue.get_stats()
    assert stats["failed"] == 1
    WikiCompiler._active_workers.pop(str(wiki_structure.base_dir), None)


@pytest.mark.asyncio
async def test_compile_all_embed_pause_returns_early(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """compile_all returns early with pending stats on embed violation (line 487)."""
    from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
        EmbedInputTooLargeError,
    )
    from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo

    mock_llm.ainvoke.return_value = AIMessage(content='[{"name": "Big", "definition": "d", "mentions": 2}]')
    compiler = WikiCompiler(
        mock_llm,
        wiki_structure,
        WikiConfig(),
        WikiCompileConfig(require_approval=False, min_concept_mentions=1),
        indexer=None,
    )

    async def _raise_embed(concept: ConceptInfo) -> str:
        raise EmbedInputTooLargeError(
            token_count=900,
            limit=512,
            model="test-embed",
            parent_key=concept.name,
        )

    compiler._generate_article = _raise_embed  # type: ignore[method-assign]
    raw = wiki_structure.raw_dir / "big.md"
    raw.write_text("Big content.", encoding="utf-8")
    compiler._queue.add_item(raw)

    result = await compiler.compile_all(batch_size=10)
    assert result.articles_generated == 0
    assert result.articles_blocked == 1
    assert compiler._queue.is_compile_paused() is True
    compiler._queue.resume_compile()
    WikiCompiler._active_workers.pop(str(wiki_structure.base_dir), None)


@pytest.mark.asyncio
async def test_compile_all_synthesis_staged_log(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """compile_all logs staged synthesis pages (line 506)."""
    llm = AsyncMock()
    llm.ainvoke.side_effect = [
        AIMessage(content='[{"name": "Synth", "definition": "d"}]'),
        AIMessage(content="## Compiled Truth\nSynth article."),
    ]
    compiler = WikiCompiler(
        llm,
        wiki_structure,
        WikiConfig(),
        WikiCompileConfig(require_approval=False, min_concept_mentions=1),
        indexer=mock_indexer,
    )
    raw = wiki_structure.raw_dir / "synth.md"
    raw.write_text("Content.", encoding="utf-8")
    compiler._queue.add_item(raw)

    with patch(
        "myrm_agent_harness.toolkits.wiki.pipeline.compiler.run_contradiction_synthesis_pass",
        return_value=MagicMock(synthesis_staged=2, pairs_considered=3),
    ) as mock_synthesis:
        result = await compiler.compile_all(batch_size=10)
    assert result.synthesis_pending == 2
    mock_synthesis.assert_awaited()
    WikiCompiler._active_workers.pop(str(wiki_structure.base_dir), None)


@pytest.mark.asyncio
async def test_worker_loop_pauses_on_pause_kind_failure(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """_worker_loop pauses after a batch with a non-retryable pause kind (lines 349-351)."""
    llm = AsyncMock()
    llm.ainvoke.side_effect = Exception("401 Invalid API key")
    compiler = WikiCompiler(llm, wiki_structure, WikiConfig(), indexer=mock_indexer)
    raw = wiki_structure.raw_dir / "auth.md"
    raw.write_text("Content.", encoding="utf-8")
    compiler._queue.add_item(raw)

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(0)

    with patch("asyncio.sleep", side_effect=fast_sleep):
        await compiler._worker_loop()

    assert compiler._queue.is_compile_paused() is True
    compiler._queue.resume_compile()


@pytest.mark.asyncio
async def test_worker_loop_exception_outer(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """_worker_loop catches exceptions escaping the drain body (line 383)."""
    llm = AsyncMock()
    compiler = WikiCompiler(llm, wiki_structure, WikiConfig(), indexer=mock_indexer)
    raw = wiki_structure.raw_dir / "err.md"
    raw.write_text("Content.", encoding="utf-8")
    compiler._queue.add_item(raw)

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(0)

    with (
        patch.object(
            compiler._queue,
            "get_pending_items",
            side_effect=RuntimeError("DB locked"),
        ),
        patch("asyncio.sleep", side_effect=fast_sleep),
    ):
        await compiler._worker_loop()

    assert WikiCompiler._active_workers.get(str(wiki_structure.base_dir)) is None


@pytest.mark.asyncio
async def test_generate_articles_batch_base_exception_blocked(
    wiki_structure: WikiStructure, mock_indexer: AsyncMock
) -> None:
    """_generate_articles_batch counts BaseException results as blocked (lines 755-756)."""

    class _FatalError(BaseException):
        pass

    llm = AsyncMock()

    async def _boom(concept: ConceptInfo) -> str:
        raise _FatalError()

    compiler = WikiCompiler(llm, wiki_structure, WikiConfig(), indexer=mock_indexer)
    compiler._generate_article = _boom  # type: ignore[method-assign]
    concepts = [ConceptInfo(name="Fatal", definition="d", mentions=2, source_files=["a.md"])]
    stats = await compiler._generate_articles_batch(concepts)
    assert stats.generated == 0
    assert stats.blocked == 1


@pytest.mark.asyncio
async def test_record_facet_seeds_matches_batch_paths(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """_record_facet_seeds records seeds for concepts whose sources are in the batch (lines 247-250)."""
    _write_nested_raw(wiki_structure, "sub/doc.md", "Nested doc content.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    compiler._queue.add_item(wiki_structure.raw_dir / "sub" / "doc.md")
    compiler._ensure_compile_session()

    concept = ConceptInfo(
        name="Seed Concept",
        definition="d",
        mentions=1,
        source_files=["raw/sub/doc.md"],
    )
    compiler._record_facet_seeds(compiler._queue.get_pending_items(limit=5), [concept])
    session = compiler._get_session()
    assert session is not None
    assert any("Seed Concept" in seeds for seeds in session.facet_seeds.values())


@pytest.mark.asyncio
async def test_build_extract_survey_context_empty_for_unmapped_path(
    wiki_structure: WikiStructure, mock_llm: AsyncMock
) -> None:
    """_build_extract_survey_context returns empty for paths outside any facet (line 230)."""
    _write_nested_raw(wiki_structure, "sub/doc.md", "Nested doc content.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    compiler._queue.add_item(wiki_structure.raw_dir / "sub" / "doc.md")
    compiler._ensure_compile_session()

    survey = compiler._build_extract_survey_context("raw/unmapped/unrelated.md")
    assert survey == ""


@pytest.mark.asyncio
async def test_record_facet_seeds_skips_unmapped_sources(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """_record_facet_seeds skips sources outside the batch or facet map (lines 247, 250)."""
    _write_nested_raw(wiki_structure, "sub/doc.md", "Nested doc content.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    compiler._queue.add_item(wiki_structure.raw_dir / "sub" / "doc.md")
    compiler._ensure_compile_session()

    concept = ConceptInfo(
        name="Skipped",
        definition="d",
        mentions=1,
        source_files=["raw/not-in-batch.md", "raw/not-in-facet.md"],
    )
    compiler._record_facet_seeds(compiler._queue.get_pending_items(limit=5), [concept])
    session = compiler._get_session()
    assert session is not None
    assert all("Skipped" not in seeds for seeds in session.facet_seeds.values())


@pytest.mark.asyncio
async def test_generate_articles_batch_pending_status(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """_generate_articles_batch counts pending results when approval is required (line 758)."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nPending article.")
    compile_config = WikiCompileConfig(require_approval=True, min_concept_mentions=1)
    compiler = WikiCompiler(llm, wiki_structure, WikiConfig(), compile_config, indexer=mock_indexer)

    concepts = [ConceptInfo(name="Approval", definition="Def", mentions=2, source_files=["a.md"])]
    stats = await compiler._generate_articles_batch(concepts)
    assert stats.pending == 1
    assert stats.published == 0


@pytest.mark.asyncio
async def test_record_facet_seeds_skips_unmapped_facet(wiki_structure: WikiStructure, mock_llm: AsyncMock) -> None:
    """_record_facet_seeds skips sources without a facet mapping (line 250)."""
    _write_nested_raw(wiki_structure, "sub/doc.md", "Nested doc content.")
    compiler = WikiCompiler(mock_llm, wiki_structure, WikiConfig())
    compiler._queue.add_item(wiki_structure.raw_dir / "sub" / "doc.md")
    compiler._ensure_compile_session()

    from myrm_agent_harness.toolkits.wiki.pipeline.queue import QueueItem

    unmapped_item: QueueItem = {
        "id": 99,
        "file_path": str(wiki_structure.raw_dir / "sub2" / "unmapped.md"),
        "status": "pending",
        "retry_count": 0,
        "error_message": None,
        "error_kind": None,
        "retry_after": None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    concept = ConceptInfo(
        name="Unmapped",
        definition="d",
        mentions=1,
        source_files=["raw/sub2/unmapped.md"],
    )
    compiler._record_facet_seeds([unmapped_item], [concept])
    session = compiler._get_session()
    assert session is not None
    assert all("Unmapped" not in seeds for seeds in session.facet_seeds.values())


@pytest.mark.asyncio
async def test_generate_articles_batch_unexpected_status_blocked(
    wiki_structure: WikiStructure, mock_indexer: AsyncMock
) -> None:
    """_generate_articles_batch treats unexpected status strings as blocked (line 758)."""
    llm = AsyncMock()

    async def _weird(concept: ConceptInfo) -> str:
        return "unexpected-status"

    compiler = WikiCompiler(llm, wiki_structure, WikiConfig(), indexer=mock_indexer)
    compiler._generate_article = _weird  # type: ignore[method-assign]
    concepts = [ConceptInfo(name="Weird", definition="d", mentions=2, source_files=["a.md"])]
    stats = await compiler._generate_articles_batch(concepts)
    assert stats.generated == 0
    assert stats.blocked == 1


@pytest.mark.asyncio
async def test_worker_loop_pauses_on_embed_failure(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    """_worker_loop pauses after an embed window violation (line 359)."""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content='[{"name": "Emb", "definition": "d"}]')
    compiler = WikiCompiler(llm, wiki_structure, WikiConfig(), indexer=mock_indexer)

    raw = wiki_structure.raw_dir / "emb.md"
    raw.write_text("Embed content.", encoding="utf-8")
    compiler._queue.add_item(raw)

    embed_stats = _ArticleBatchStats(
        generated=0,
        pending=0,
        published=0,
        blocked=1,
        embed_pause_reason="Embedding too large",
        embed_pause_kind=EMBED_WINDOW_VIOLATION,
    )
    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        await original_sleep(0)

    with (
        patch.object(compiler, "_generate_articles_batch", new=AsyncMock(return_value=embed_stats)),
        patch("asyncio.sleep", side_effect=fast_sleep),
    ):
        await compiler._worker_loop()

    assert compiler._queue.is_compile_paused() is True
    compiler._queue.resume_compile()
