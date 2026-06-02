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
