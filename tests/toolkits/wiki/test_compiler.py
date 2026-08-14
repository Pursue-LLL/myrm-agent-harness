from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
    parse_claims_from_content,
)
from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def wiki_structure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content="## Compiled Truth\nGenerated article content."
    )
    return llm


@pytest.fixture
def mock_indexer():
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    return indexer


@pytest.mark.asyncio
async def test_wiki_compiler_generate_article(wiki_structure, mock_llm, mock_indexer):
    config = WikiConfig()
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(
        mock_llm, wiki_structure, config, compile_config, indexer=mock_indexer
    )

    # We mock _generate_article directly since process() might involve multiple steps
    # We can test process but let's test the core generation first
    class DummyConcept:
        name = "Test Concept"
        reason = "test"
        source_files = ("test.md",)

    await compiler._generate_article(DummyConcept())

    # Verify file is written with structured claims
    article_path = wiki_structure.get_concept_file_path("Test Concept")
    assert article_path.exists()
    saved = article_path.read_text(encoding="utf-8")
    assert "Generated article content." in saved
    claims = parse_claims_from_content(saved)
    assert len(claims) == 1
    assert claims[0].evidence[0].path == "test.md"

    # Verify indexer is called
    mock_indexer.upsert.assert_awaited_once()
    upsert_content = mock_indexer.upsert.await_args.args[1]
    assert "Generated article content." in upsert_content
    assert parse_claims_from_content(upsert_content)


@pytest.mark.asyncio
async def test_wiki_compiler_require_approval(wiki_structure, mock_llm, mock_indexer):
    config = WikiConfig()
    compile_config = WikiCompileConfig(require_approval=True)
    compiler = WikiCompiler(
        mock_llm, wiki_structure, config, compile_config, indexer=mock_indexer
    )

    class DummyConcept:
        name = "Test Concept"
        reason = "test"
        source_files = ("test.md",)

    await compiler._generate_article(DummyConcept())

    # File should not exist directly
    article_path = wiki_structure.get_concept_file_path("Test Concept")
    assert not article_path.exists()

    # Indexer should NOT be called directly
    mock_indexer.upsert.assert_not_called()

    # Instead, check if pending edit was added
    from myrm_agent_harness.toolkits.wiki.pipeline.pending import (
        WikiPendingEditsManager,
    )

    mgr = WikiPendingEditsManager(wiki_structure)
    edits = mgr.get_pending_edits()
    assert len(edits) == 1
    assert edits[0]["concept_name"] == "Test Concept"
    assert parse_claims_from_content(edits[0]["proposed_content"])


@pytest.mark.asyncio
async def test_extract_concepts_from_doc(wiki_structure, mock_llm, mock_indexer):
    """_extract_concepts_from_doc parses an LLM concept list from a raw doc."""
    from myrm_agent_harness.toolkits.wiki.core.config import (
        WikiCompileConfig,
        WikiConfig,
    )

    compiler = WikiCompiler(
        mock_llm,
        wiki_structure,
        WikiConfig(),
        WikiCompileConfig(require_approval=False, min_concept_mentions=1),
        indexer=mock_indexer,
    )
    raw_dir = wiki_structure.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    doc_path = raw_dir / "architecture.md"
    doc_path.write_text("# Architecture\n\nSystem design notes.", encoding="utf-8")

    mock_llm.ainvoke.return_value = AIMessage(
        content=(
            '[{"name": "API Gateway", "definition": "Entry point", "mentions": 3, '
            '"source_files": ["architecture.md"], "related_concepts": []}]'
        )
    )
    concepts = await compiler._extract_concepts_from_doc(doc_path)
    assert len(concepts) == 1
    assert concepts[0].name == "API Gateway"


@pytest.mark.asyncio
async def test_extract_concepts_from_doc_reasoning_fallback(
    wiki_structure, mock_llm, mock_indexer
):
    """_extract_concepts_from_doc falls back to reasoning_content when content is empty."""
    from myrm_agent_harness.toolkits.wiki.core.config import (
        WikiCompileConfig,
        WikiConfig,
    )

    compiler = WikiCompiler(
        mock_llm,
        wiki_structure,
        WikiConfig(),
        WikiCompileConfig(require_approval=False, min_concept_mentions=1),
        indexer=mock_indexer,
    )
    raw_dir = wiki_structure.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    doc_path = raw_dir / "architecture.md"
    doc_path.write_text("# Architecture\n\nSystem design notes.", encoding="utf-8")

    mock_llm.ainvoke.return_value = MagicMock(
        content="",
        additional_kwargs={
            "reasoning_content": (
                '[{"name": "API Gateway", "definition": "Entry point", "mentions": 3, '
                '"source_files": ["architecture.md"], "related_concepts": []}]'
            )
        },
    )
    concepts = await compiler._extract_concepts_from_doc(doc_path)
    assert len(concepts) == 1
    assert concepts[0].name == "API Gateway"


@pytest.mark.asyncio
async def test_extract_concepts_from_doc_unreadable(
    wiki_structure, mock_llm, mock_indexer
):
    """_extract_concepts_from_doc returns [] for an unreadable doc without raising."""
    from myrm_agent_harness.toolkits.wiki.core.config import (
        WikiCompileConfig,
        WikiConfig,
    )

    compiler = WikiCompiler(
        mock_llm,
        wiki_structure,
        WikiConfig(),
        WikiCompileConfig(require_approval=False, min_concept_mentions=1),
        indexer=mock_indexer,
    )
    doc_path = wiki_structure.raw_dir / "missing.md"
    concepts = await compiler._extract_concepts_from_doc(doc_path)
    assert concepts == []
    from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
        EmbedInputTooLargeError,
    )
    from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
    from myrm_agent_harness.toolkits.wiki.pipeline.resilience import (
        EMBED_WINDOW_VIOLATION,
    )

    compiler = WikiCompiler(
        mock_llm,
        wiki_structure,
        WikiConfig(),
        WikiCompileConfig(require_approval=False, min_concept_mentions=1),
        indexer=mock_indexer,
    )

    async def _raise_embed(concept: ConceptInfo) -> str:
        raise EmbedInputTooLargeError(
            token_count=900,
            limit=512,
            model="test-embed",
            parent_key=concept.name,
        )

    compiler._generate_article = _raise_embed  # type: ignore[method-assign]

    concepts = [
        ConceptInfo(
            name="Big Doc",
            definition="large compiled truth",
            mentions=1,
            source_files=["a.md"],
        )
    ]
    stats = await compiler._generate_articles_batch(concepts)

    assert stats.embed_pause_kind == EMBED_WINDOW_VIOLATION
    assert "900" in stats.embed_pause_reason
    assert stats.blocked == 1


def _restore_provenance_metadata(existing_content: str, new_content: str) -> str:
    from myrm_agent_harness.toolkits.wiki.pipeline.compiler_provenance import (
        restore_provenance_metadata,
    )

    return restore_provenance_metadata(existing_content, new_content)


def test_restore_provenance_metadata_backfills_lost_source_chat():
    existing = (
        "---\ntype: concept\nsource_chat: chat-abc\ncompound_provenance: chat-compound\n---\n"
        "## Compiled Truth\nold\n"
    )
    new_llm_output = (
        "---\ntype: concept\n---\n## Compiled Truth\nnew\n## Timeline\n- entry\n"
    )
    restored = _restore_provenance_metadata(existing, new_llm_output)
    assert "source_chat: chat-abc" in restored
    assert "compound_provenance: chat-compound" in restored
    assert "## Timeline" in restored


def test_restore_provenance_metadata_keeps_existing_authoritative():
    existing = (
        "---\ntype: concept\nsource_chat: chat-abc\n---\n## Compiled Truth\nold\n"
    )
    new_llm_output = (
        "---\ntype: concept\nsource_chat: chat-different\n---\n## Compiled Truth\nnew\n"
    )
    restored = _restore_provenance_metadata(existing, new_llm_output)
    assert "source_chat: chat-abc" in restored
    assert "chat-different" not in restored


def test_restore_provenance_metadata_noop_without_existing_provenance():
    existing = "---\ntype: concept\n---\n## Compiled Truth\nold\n"
    new_llm_output = "---\ntype: concept\n---\n## Compiled Truth\nnew\n"
    assert _restore_provenance_metadata(existing, new_llm_output) == new_llm_output


def test_restore_provenance_metadata_noop_without_existing_content():
    new_llm_output = "---\ntype: concept\n---\n## Compiled Truth\nnew\n"
    assert _restore_provenance_metadata("", new_llm_output) == new_llm_output


def test_provenance_from_raw_sources_single_chat(wiki_structure: WikiStructure):
    """First-compile backfill: raw turn files with one agreeing source_chat."""
    from myrm_agent_harness.toolkits.wiki.pipeline.compiler_provenance import (
        provenance_from_raw_sources,
    )

    raw_dir = wiki_structure.raw_dir
    raw_dir.joinpath("turn_chat-a_a.md").write_text(
        "---\nsource_chat: chat-a\n---\n# Turn\n", encoding="utf-8"
    )
    raw_dir.joinpath("turn_chat-a_b.md").write_text(
        "---\nsource_chat: chat-a\n---\n# Turn\n", encoding="utf-8"
    )

    provenance = provenance_from_raw_sources(
        wiki_structure, ["turn_chat-a_a.md", "turn_chat-a_b.md"]
    )
    assert provenance == {"source_chat": "chat-a"}


def test_provenance_from_raw_sources_vault_relative_prefix(wiki_structure: WikiStructure):
    """source_files derived from vault-relative paths (raw/...) must resolve too."""
    from myrm_agent_harness.toolkits.wiki.pipeline.compiler_provenance import (
        provenance_from_raw_sources,
    )

    raw_dir = wiki_structure.raw_dir
    raw_dir.joinpath("turn_chat-a_a.md").write_text(
        "---\nsource_chat: chat-a\n---\n# Turn\n", encoding="utf-8"
    )

    provenance = provenance_from_raw_sources(
        wiki_structure, ["raw/turn_chat-a_a.md"]
    )
    assert provenance == {"source_chat": "chat-a"}


def test_provenance_from_raw_sources_conflicting_chats(wiki_structure: WikiStructure):
    """Multiple unrelated chats must not produce a single misleading source_chat."""
    from myrm_agent_harness.toolkits.wiki.pipeline.compiler_provenance import (
        provenance_from_raw_sources,
    )

    raw_dir = wiki_structure.raw_dir
    raw_dir.joinpath("turn_chat-a_a.md").write_text(
        "---\nsource_chat: chat-a\n---\n# Turn\n", encoding="utf-8"
    )
    raw_dir.joinpath("turn_chat-b_b.md").write_text(
        "---\nsource_chat: chat-b\n---\n# Turn\n", encoding="utf-8"
    )

    provenance = provenance_from_raw_sources(
        wiki_structure, ["turn_chat-a_a.md", "turn_chat-b_b.md"]
    )
    assert provenance == {}


def test_provenance_from_raw_sources_missing_file(wiki_structure: WikiStructure):
    """Missing or non-provenance raw files contribute nothing."""
    from myrm_agent_harness.toolkits.wiki.pipeline.compiler_provenance import (
        provenance_from_raw_sources,
    )

    raw_dir = wiki_structure.raw_dir
    raw_dir.joinpath("note.md").write_text(
        "---\nsource_url: https://example.com\n---\n# Note\n", encoding="utf-8"
    )

    provenance = provenance_from_raw_sources(wiki_structure, ["note.md", "missing.md"])
    assert provenance == {}
