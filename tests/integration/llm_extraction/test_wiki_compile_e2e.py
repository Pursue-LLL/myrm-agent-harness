"""Real-LLM e2e tests for the wiki compile pipeline content extraction.

Exercises the reasoning-model-aware extraction inside ``WikiCompiler``: concept
extraction from a raw document and article generation both go through
``extract_answer_text``. No mocks on the LLM path.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler

pytestmark = pytest.mark.e2e


def _make_structure(tmp_path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.mark.asyncio
async def test_extract_concepts_from_doc_real_llm(tmp_path, basic_llm) -> None:
    """A real LLM extracts non-empty concepts from a Chinese business document."""
    structure = _make_structure(tmp_path)
    compiler = WikiCompiler(basic_llm, structure, WikiConfig(), WikiCompileConfig())
    raw = structure.raw_dir / "marketing.md"
    raw.write_text(
        "# 市场营销\n\n事件营销是一种通过制造热点事件来提升品牌知名度的策略。社交裂变利用用户分享实现低成本获客。",
        encoding="utf-8",
    )

    concepts = await compiler._extract_concepts_from_doc(raw)
    assert isinstance(concepts, list)
    assert concepts, "real LLM should extract at least one concept from the document"
    assert all(isinstance(c, ConceptInfo) for c in concepts)
    assert all(c.name for c in concepts)


@pytest.mark.asyncio
async def test_generate_article_real_llm(tmp_path, basic_llm) -> None:
    """A real LLM generates a non-empty wiki article file."""
    structure = _make_structure(tmp_path)
    compiler = WikiCompiler(
        basic_llm,
        structure,
        WikiConfig(),
        WikiCompileConfig(require_approval=False),
    )
    concept = ConceptInfo(
        name="事件营销",
        definition="通过制造热点事件提升品牌知名度",
        mentions=2,
        source_files=["raw/marketing.md"],
    )

    status = await compiler._generate_article(concept)
    assert status in {"pending", "published"}
    article_path = structure.get_concept_file_path("事件营销")
    assert article_path.exists(), "article file should be written by the real LLM path"
    content = article_path.read_text(encoding="utf-8")
    assert content.strip(), "article file should not be empty"


@pytest.mark.asyncio
async def test_compile_all_full_pipeline_real_llm(tmp_path, basic_llm) -> None:
    """compile_all drives the full queue -> extract -> generate pipeline with a real LLM."""
    structure = _make_structure(tmp_path)
    raw = structure.raw_dir / "marketing.md"
    raw.write_text(
        "# 市场营销\n\n事件营销是一种通过制造热点事件来提升品牌知名度的策略。社交裂变利用用户分享实现低成本获客。",
        encoding="utf-8",
    )

    config = WikiConfig(
        enable_backlinks=False,
        enable_directory_sidecars=False,
        enable_semantic_search=False,
        enable_hybrid_search=False,
        parallel_compilation=False,
    )
    compiler = WikiCompiler(
        basic_llm,
        structure,
        config,
        WikiCompileConfig(require_approval=False, min_concept_mentions=1),
    )

    result = await compiler.compile_all(batch_size=10)
    assert result.concepts_count > 0, "compile_all should extract concepts from the doc"
    assert result.articles_generated > 0, "compile_all should generate articles"
    assert result.articles_published + result.articles_pending > 0

    concepts_dir = structure.concepts_dir
    generated = list(concepts_dir.rglob("*.md")) if concepts_dir.exists() else []
    assert generated, "concept article files should be written under concepts/"
    for article in generated:
        assert article.read_text(encoding="utf-8").strip(), f"article {article} must not be empty"
