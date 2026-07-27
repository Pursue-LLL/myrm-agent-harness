"""Integration test: sidecar build → index → query full pipeline (real LLM)."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig, WikiQueryConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.sidecar import build_directory_sidecars
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
from myrm_agent_harness.toolkits.wiki.retrieval.query import WikiQueryEngine

_ENV_TEST = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "..",
    "myrm-agent", "myrm-agent-server", ".env.test",
)
load_dotenv(_ENV_TEST, override=False)


def _get_test_llm():
    """Create a real LLM instance from .env.test credentials."""
    from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model

    model = os.getenv("BASIC_MODEL") or os.getenv("LITE_MODEL")
    api_key = os.getenv("BASIC_API_KEY") or os.getenv("LITE_API_KEY")
    base_url = os.getenv("BASIC_BASE_URL") or os.getenv("LITE_BASE_URL")
    if not model or not api_key:
        pytest.skip("No LLM credentials in .env.test")
    return create_litellm_model(
        model=model,
        api_key=api_key,
        api_base=base_url,
        temperature=0,
        max_tokens=1024,
    )


def _seed_concepts(structure: WikiStructure) -> list[ConceptInfo]:
    """Create minimal wiki concept files for testing."""
    concepts = [
        ("ML/Transformers", "Transformer architecture uses self-attention mechanism for sequence modeling."),
        ("ML/BERT", "BERT is a bidirectional encoder pre-trained on masked language modeling."),
        ("Systems/Kubernetes", "Kubernetes orchestrates containerized applications across clusters."),
    ]
    infos: list[ConceptInfo] = []
    for name, truth in concepts:
        path = structure.get_concept_file_path(name)
        path.write_text(
            f"---\ntags: [test]\n---\n## Compiled Truth\n{truth}\n## Timeline\n- Initial entry.",
            encoding="utf-8",
        )
        infos.append(ConceptInfo(name=name, definition=truth[:60], source_files=["test.md"], related_concepts=[]))
    return infos


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_sidecar_build_index_query_pipeline(tmp_path):
    """Full pipeline: seed concepts → build sidecars → index → query via sidecar routing."""
    llm = _get_test_llm()

    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    config = WikiConfig(enable_hybrid_search=False, enable_directory_sidecars=True)
    indexer = WikiIndexer(structure, config)

    concepts = _seed_concepts(structure)
    for concept in concepts:
        path = structure.get_concept_file_path(concept.name)
        content = path.read_text(encoding="utf-8")
        await indexer.upsert(concept.name, content)
        indexer.extract_and_upsert_edges(concept.name, content)

    result = await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=concepts,
        indexer=indexer,
    )
    assert result.rebuilt_directories >= 2, f"Expected ≥2 rebuilt directories, got {result.rebuilt_directories}"
    assert result.skipped_directories == 0

    abstract_ml, overview_ml = structure.get_directory_sidecar_paths("ml", create=False)
    assert abstract_ml.exists(), "ML directory L0 sidecar should exist"
    assert overview_ml.exists(), "ML directory L1 sidecar should exist"

    abstract_content = abstract_ml.read_text(encoding="utf-8")
    assert len(abstract_content) > 10, "L0 abstract should have meaningful content"

    sidecar_hits = await indexer.search_sidecars("transformer attention", limit=5)
    assert len(sidecar_hits) >= 1, "Sidecar search should find ML directory"

    ml_dirs = [dir_path for dir_path, _, _ in sidecar_hits]
    assert "ml" in ml_dirs, f"Expected 'ml' in sidecar hits, got {ml_dirs}"

    query_config = WikiQueryConfig(
        sidecar_retrieval_enabled=True,
        max_sidecar_directories=3,
        max_full_articles=3,
        max_context_chars=12000,
        max_context_articles=5,
    )
    query_engine = WikiQueryEngine(llm, structure, config, query_config)
    query_result = await query_engine.query("What is the transformer architecture?")

    assert len(query_result.related_articles) >= 1, "Query should find related articles"
    assert query_result.answer, "Query should produce an answer"
    assert query_result.confidence_score > 0, "Confidence should be positive"


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_sidecar_incremental_rebuild_skips_unchanged(tmp_path):
    """Second build with no changes should skip all directories."""
    llm = _get_test_llm()

    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    config = WikiConfig(enable_hybrid_search=False, enable_directory_sidecars=True)
    indexer = WikiIndexer(structure, config)
    concepts = _seed_concepts(structure)

    first = await build_directory_sidecars(
        llm, structure, WikiCompileConfig(), touched_concepts=concepts, indexer=indexer,
    )
    assert first.rebuilt_directories >= 2

    llm_call_count_before = llm.ainvoke.call_count if hasattr(llm.ainvoke, "call_count") else None

    second = await build_directory_sidecars(
        llm, structure, WikiCompileConfig(), touched_concepts=[], indexer=indexer,
    )
    assert second.skipped_directories >= 2, "All directories should be skipped on second build"
    assert second.rebuilt_directories == 0, "No directories should be rebuilt"


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_sidecar_isolation_from_concept_search(tmp_path):
    """Sidecar entries must not appear in L2 concept search results."""
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(structure, config)

    await indexer.upsert("ML/NLP", "## Compiled Truth\nNatural language processing fundamentals.")
    await indexer.upsert_sidecar("ml", level=0, content="Machine learning directory abstract.")
    await indexer.upsert_sidecar("ml", level=1, content="Machine learning directory overview.")

    concept_results = await indexer.search("machine learning", limit=10)
    for concept_name, _ in concept_results:
        assert not concept_name.startswith("__sidecar__"), f"Sidecar leaked into concept search: {concept_name}"

    sidecar_results = await indexer.search_sidecars("machine learning", limit=10)
    assert len(sidecar_results) >= 1, "Sidecar search should find ml directory"
    assert sidecar_results[0][0] == "ml"
