"""Tests for WikiLinter."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.wiki import (
    WikiConfig,
    WikiLinter,
    WikiStructure,
)


@pytest.fixture
def temp_wiki_dir(tmp_path: Path) -> Path:
    """Create temporary wiki directory."""
    wiki_dir = tmp_path / "test-wiki"
    return wiki_dir


@pytest.fixture
def wiki_structure(temp_wiki_dir: Path) -> WikiStructure:
    """Create WikiStructure instance with sample concepts."""
    structure = WikiStructure(temp_wiki_dir)
    structure.ensure_structure()

    short_concept = structure.get_concept_file_path("Short Article")
    short_concept.write_text("# Short Article\n\nShort.")

    broken_link_concept = structure.get_concept_file_path("Broken Links")
    broken_link_concept.write_text("# Broken Links\n\n[Missing](missing.md) [External](https://example.com)")

    todo_concept = structure.get_concept_file_path("TODO Article")
    todo_concept.write_text("# TODO Article\n\nTODO: Add more content")

    return structure


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create mock LLM."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock()
    return llm


@pytest.fixture
def linter(
    mock_llm: MagicMock,
    wiki_structure: WikiStructure,
) -> WikiLinter:
    """Create WikiLinter instance."""
    config = WikiConfig(enable_auto_maintenance=False)
    return WikiLinter(mock_llm, wiki_structure, config)


@pytest.mark.asyncio
async def test_check_broken_links(linter: WikiLinter) -> None:
    """Test broken link detection."""
    issues = await linter._check_broken_links()

    assert len(issues) >= 1
    assert any(issue.issue_type == "broken_link" for issue in issues)


@pytest.mark.asyncio
async def test_check_completeness_finds_short_articles(linter: WikiLinter) -> None:
    """Test completeness check finds short articles."""
    issues = await linter._check_completeness()

    assert len(issues) >= 1
    assert any(issue.issue_type == "incomplete" and "short" in issue.description.lower() for issue in issues)


@pytest.mark.asyncio
async def test_check_completeness_finds_todos(linter: WikiLinter) -> None:
    """Test completeness check finds TODO markers."""
    issues = await linter._check_completeness()

    assert any(issue.issue_type == "incomplete" and "TODO" in issue.description for issue in issues)


@pytest.mark.asyncio
async def test_lint_and_maintain(
    linter: WikiLinter,
    mock_llm: MagicMock,
) -> None:
    """Test full linting and maintenance."""
    result = await linter.lint_and_maintain()

    assert result.issues_found >= 0
    assert result.issues_fixed >= 0
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_lint_and_maintain_knowledge_gaps(
    mock_llm: MagicMock,
    wiki_structure: WikiStructure,
) -> None:
    """Test that Check 6 produces knowledge_gap issues from graph insights."""
    mock_indexer = MagicMock()
    mock_indexer.graph_insights.return_value = {
        "knowledge_gaps": [
            {"node": "Orphan Topic", "type": "isolated", "degree": 0},
            {"node": "Hub Topic", "type": "bridge", "communities_connected": 4},
        ],
        "unexpected_connections": [],
        "communities": [],
    }
    config = WikiConfig(enable_auto_maintenance=False)
    linter_with_indexer = WikiLinter(mock_llm, wiki_structure, config, indexer=mock_indexer)

    result = await linter_with_indexer.lint_and_maintain()

    gap_issues = [i for i in result.issues if i.issue_type == "knowledge_gap"]
    assert len(gap_issues) == 2
    assert gap_issues[0].location == "Orphan Topic"
    assert "Isolated" in gap_issues[0].description
    assert gap_issues[1].location == "Hub Topic"
    assert "Bridge" in gap_issues[1].description
    mock_indexer.graph_insights.assert_called_once()


@pytest.mark.asyncio
async def test_lint_knowledge_gaps_exception_safe(
    mock_llm: MagicMock,
    wiki_structure: WikiStructure,
) -> None:
    """Check 6 gracefully handles graph_insights() exceptions."""
    mock_indexer = MagicMock()
    mock_indexer.graph_insights.side_effect = RuntimeError("db locked")
    config = WikiConfig(enable_auto_maintenance=False)
    linter_err = WikiLinter(mock_llm, wiki_structure, config, indexer=mock_indexer)

    result = await linter_err.lint_and_maintain()

    assert not any(i.issue_type == "knowledge_gap" for i in result.issues)
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_lint_knowledge_gaps_empty(
    mock_llm: MagicMock,
    wiki_structure: WikiStructure,
) -> None:
    """Check 6 with empty knowledge_gaps produces no issues."""
    mock_indexer = MagicMock()
    mock_indexer.graph_insights.return_value = {
        "knowledge_gaps": [],
        "unexpected_connections": [],
        "communities": [],
    }
    config = WikiConfig(enable_auto_maintenance=False)
    linter_empty = WikiLinter(mock_llm, wiki_structure, config, indexer=mock_indexer)

    result = await linter_empty.lint_and_maintain()

    assert not any(i.issue_type == "knowledge_gap" for i in result.issues)


@pytest.mark.asyncio
async def test_lint_knowledge_gaps_unknown_type_ignored(
    mock_llm: MagicMock,
    wiki_structure: WikiStructure,
) -> None:
    """Check 6 ignores gap entries with unknown type."""
    mock_indexer = MagicMock()
    mock_indexer.graph_insights.return_value = {
        "knowledge_gaps": [
            {"node": "X", "type": "unknown_future_type"},
            {"node": "Y", "type": "isolated", "degree": 1},
        ],
        "unexpected_connections": [],
        "communities": [],
    }
    config = WikiConfig(enable_auto_maintenance=False)
    linter_mixed = WikiLinter(mock_llm, wiki_structure, config, indexer=mock_indexer)

    result = await linter_mixed.lint_and_maintain()

    gap_issues = [i for i in result.issues if i.issue_type == "knowledge_gap"]
    assert len(gap_issues) == 1
    assert gap_issues[0].location == "Y"


@pytest.mark.asyncio
async def test_discover_connections(
    linter: WikiLinter,
    wiki_structure: WikiStructure,
) -> None:
    """Test connection discovery between concepts."""
    concept1 = wiki_structure.get_concept_file_path("Concept A")
    concept1.write_text("# Concept A\n\nRefers to Concept B")

    concept2 = wiki_structure.get_concept_file_path("Concept B")
    concept2.write_text("# Concept B\n\nStandalone concept")

    connections = await linter._discover_connections()

    assert connections >= 0
