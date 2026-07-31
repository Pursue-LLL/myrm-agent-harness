"""Tests for SCHEMA.md writer and compile index context reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import WIKI_PAGE_TYPES
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.schema_writer import (
    read_index_context,
    render_schema_markdown,
    write_schema_markdown,
)


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


def test_render_schema_markdown_lists_all_page_types() -> None:
    body = render_schema_markdown()
    for page_type in sorted(WIKI_PAGE_TYPES):
        assert f"`{page_type}`" in body


def test_write_schema_markdown_creates_file(wiki_structure: WikiStructure) -> None:
    schema_path = write_schema_markdown(wiki_structure)
    assert schema_path == wiki_structure.get_schema_file_path()
    assert schema_path.is_file()
    assert "Page types" in schema_path.read_text(encoding="utf-8")


def test_read_index_context_returns_empty_when_missing(wiki_structure: WikiStructure) -> None:
    assert read_index_context(wiki_structure) == ""


def test_read_index_context_truncates_large_index(wiki_structure: WikiStructure) -> None:
    index_path = wiki_structure.get_index_file_path()
    index_path.write_text("x" * 5_000, encoding="utf-8")
    context = read_index_context(wiki_structure, max_chars=100)
    assert context.endswith("[truncated]")
    assert len(context) < 200


def test_cognitive_map_refresh_writes_schema(wiki_structure: WikiStructure) -> None:
    from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.events import WikiMapEvent, WikiMapEventType
    from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.writer import WikiCognitiveMapService

    service = WikiCognitiveMapService(wiki_structure)
    result = service.refresh(
        WikiMapEvent(
            event_type=WikiMapEventType.MAINTAIN,
            summary="test maintain refresh",
        )
    )
    assert result.schema_path.is_file()
    assert "Page types" in result.schema_path.read_text(encoding="utf-8")
