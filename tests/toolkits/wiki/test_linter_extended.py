"""Extended tests for WikiLinter - covering _check_stale, _check_drift, _check_consistency,
_auto_fix_issue, _discover_connections (LLM), and _extract_frontmatter_sources."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki import WikiConfig, WikiLinter, WikiStructure


@pytest.fixture
def temp_wiki(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="NO_DRIFT"))
    return llm


@pytest.fixture
def linter_auto(mock_llm: MagicMock, temp_wiki: WikiStructure) -> WikiLinter:
    config = WikiConfig(enable_auto_maintenance=True, enable_backlinks=False)
    return WikiLinter(mock_llm, temp_wiki, config)


# --- _extract_frontmatter_sources ---


def test_extract_frontmatter_sources_basic():
    content = "---\ntitle: Test\nsources:\n  - file1.md\n  - file2.md\ntags: [a]\n---\n## Compiled Truth\nContent"
    sources = WikiLinter._extract_frontmatter_sources(content)
    assert sources == ["file1.md", "file2.md"]


def test_extract_frontmatter_sources_empty():
    content = "No frontmatter here"
    sources = WikiLinter._extract_frontmatter_sources(content)
    assert sources == []


def test_extract_frontmatter_sources_no_sources_key():
    content = "---\ntitle: Test\ntags: [a]\n---\nContent"
    sources = WikiLinter._extract_frontmatter_sources(content)
    assert sources == []


def test_extract_frontmatter_sources_quoted():
    content = "---\nsources:\n  - 'file with spaces.md'\n  - \"another.md\"\n---\nContent"
    sources = WikiLinter._extract_frontmatter_sources(content)
    assert sources == ["file with spaces.md", "another.md"]


# --- _check_stale ---


@pytest.mark.asyncio
async def test_check_stale_no_metadata(linter_auto: WikiLinter) -> None:
    issues = await linter_auto._check_stale()
    assert issues == []


@pytest.mark.asyncio
async def test_check_stale_detects_updated_raw(linter_auto: WikiLinter, temp_wiki: WikiStructure) -> None:
    raw_file = temp_wiki.raw_dir / "test.md"
    raw_file.write_text("raw content")

    metadata_path = temp_wiki.get_wiki_metadata_path()
    old_time = datetime(2020, 1, 1, tzinfo=UTC).isoformat()
    stale_pin = "0" * 64
    metadata_path.write_text(
        json.dumps(
            {
                "last_compile_time": old_time,
                "last_compile_raw_hashes": {"raw/test.md": stale_pin},
            }
        )
    )

    issues = await linter_auto._check_stale()
    assert len(issues) >= 1
    assert issues[0].issue_type == "stale"


@pytest.mark.asyncio
async def test_check_stale_no_stale_when_fresh(linter_auto: WikiLinter, temp_wiki: WikiStructure) -> None:
    import hashlib

    raw_file = temp_wiki.raw_dir / "test.md"
    raw_content = "raw content"
    raw_file.write_text(raw_content)

    metadata_path = temp_wiki.get_wiki_metadata_path()
    future_time = datetime(2099, 1, 1, tzinfo=UTC).isoformat()
    current_hash = hashlib.sha256(raw_content.encode()).hexdigest()
    metadata_path.write_text(
        json.dumps(
            {
                "last_compile_time": future_time,
                "last_compile_raw_hashes": {"raw/test.md": current_hash},
            }
        )
    )

    issues = await linter_auto._check_stale()
    assert len(issues) == 0


# --- _check_drift ---


@pytest.mark.asyncio
async def test_check_drift_no_concepts(linter_auto: WikiLinter) -> None:
    issues = await linter_auto._check_drift()
    assert issues == []


@pytest.mark.asyncio
async def test_check_drift_no_drift(mock_llm: MagicMock, linter_auto: WikiLinter, temp_wiki: WikiStructure) -> None:
    concept = temp_wiki.get_concept_file_path("Test Drift")
    concept.write_text("---\nsources:\n  - source.md\n---\n## Compiled Truth\nFact A is 42%.\n## Timeline\n")

    raw_file = temp_wiki.raw_dir / "source.md"
    raw_file.write_text("Fact A is 42%.")

    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="NO_DRIFT"))
    issues = await linter_auto._check_drift()
    assert all(i.issue_type != "drift" for i in issues)


@pytest.mark.asyncio
async def test_check_drift_detects_drift(
    mock_llm: MagicMock, linter_auto: WikiLinter, temp_wiki: WikiStructure
) -> None:
    concept = temp_wiki.get_concept_file_path("Drifted")
    concept.write_text("---\nsources:\n  - source.md\n---\n## Compiled Truth\nFact A is 50%.\n## Timeline\n")

    raw_file = temp_wiki.raw_dir / "source.md"
    raw_file.write_text("Fact A is 42%.")

    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Discrepancy: wiki says 50% but source says 42%"))
    issues = await linter_auto._check_drift()
    assert any(i.issue_type == "drift" for i in issues)


# --- _auto_fix_issue ---


@pytest.mark.asyncio
async def test_incomplete_article_not_auto_fixed(
    mock_llm: MagicMock, linter_auto: WikiLinter, temp_wiki: WikiStructure
) -> None:
    concept = temp_wiki.get_concept_file_path("Short")
    concept.write_text("Short.")

    from myrm_agent_harness.toolkits.wiki.core.types import LintIssue

    issue = LintIssue(
        issue_type="incomplete",
        severity="low",
        location=str(concept),
        description="Too short",
        can_auto_fix=False,
        suggested_fix="Enhance",
    )

    await linter_auto._auto_fix_issue(issue)
    assert concept.read_text() == "Short."
    mock_llm.ainvoke.assert_not_called()


# --- _discover_connections (LLM-driven) ---


@pytest.mark.asyncio
async def test_discover_connections_llm(mock_llm: MagicMock, temp_wiki: WikiStructure) -> None:
    config = WikiConfig(enable_auto_maintenance=False, enable_backlinks=True)
    linter = WikiLinter(mock_llm, temp_wiki, config)

    c1 = temp_wiki.get_concept_file_path("Alpha")
    c1.write_text("---\ntype: concept\n---\n\n# Alpha\n\nAlpha is about ML.\n## Compiled Truth\nML content.")

    c2 = temp_wiki.get_concept_file_path("Beta")
    c2.write_text("---\ntype: concept\n---\n\n# Beta\n\nBeta is about ML.\n## Compiled Truth\nRelated content.")

    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content='["Beta"]'))
    connections = await linter._discover_connections()
    assert connections >= 1
    # Verify wikilink was added to Alpha
    assert "[[Beta]]" in c1.read_text()


@pytest.mark.asyncio
async def test_discover_connections_reasoning_model_content_empty(
    mock_llm: MagicMock, temp_wiki: WikiStructure
) -> None:
    """Reasoning 模型 content 为空时回退到 additional_kwargs["reasoning_content"]。"""
    config = WikiConfig(enable_auto_maintenance=False, enable_backlinks=True)
    linter = WikiLinter(mock_llm, temp_wiki, config)

    c1 = temp_wiki.get_concept_file_path("Alpha")
    c1.write_text("---\ntype: concept\n---\n\n# Alpha\n\nAlpha is about ML.\n## Compiled Truth\nML content.")

    c2 = temp_wiki.get_concept_file_path("Beta")
    c2.write_text("---\ntype: concept\n---\n\n# Beta\n\nBeta is about ML.\n## Compiled Truth\nRelated content.")

    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(content="", additional_kwargs={"reasoning_content": '["Beta"]'})
    )
    connections = await linter._discover_connections()
    assert connections >= 1
    assert "[[Beta]]" in c1.read_text()
