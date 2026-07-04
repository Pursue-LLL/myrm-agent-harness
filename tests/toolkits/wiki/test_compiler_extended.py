"""Extended tests for WikiCompiler - covering _filter_changed_files, compile_all,
_extract_concepts_from_doc, _parse_concepts_response, _build_index, _generate_backlinks,
_save_metadata, and purpose injection."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
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
