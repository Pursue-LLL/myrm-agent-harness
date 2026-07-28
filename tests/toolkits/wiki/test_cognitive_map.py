"""Tests for OKF cognitive map writers (index.md, log.md, hot.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map import (
    WikiCognitiveMapService,
    WikiMapEvent,
    WikiMapEventType,
    count_log_entries,
    hot_updated_at_iso,
    read_hot_context,
)


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


def test_write_index_log_hot_on_refresh(wiki_structure: WikiStructure) -> None:
    concept_path = wiki_structure.get_concept_file_path("alpha-topic")
    concept_path.write_text(
        "---\ntype: concept\n---\n# Alpha Topic\nFirst concept about testing.\n",
        encoding="utf-8",
    )

    service = WikiCognitiveMapService(wiki_structure)
    result = service.refresh(
        WikiMapEvent(
            event_type=WikiMapEventType.COMPILE,
            summary="Test compile refresh",
            details={"concepts_extracted": 1},
        )
    )

    assert result.index_path == wiki_structure.get_index_file_path()
    assert result.index_path.exists()
    index_text = result.index_path.read_text(encoding="utf-8")
    assert "[[alpha-topic]]" in index_text
    assert "## concept" in index_text

    assert result.log_path.exists()
    assert count_log_entries(wiki_structure) == 1

    assert result.hot_path.exists()
    hot_text = result.hot_path.read_text(encoding="utf-8")
    assert "Recent operations" in hot_text
    assert hot_updated_at_iso(wiki_structure) is not None
    assert "Test compile refresh" in read_hot_context(wiki_structure)


def test_index_uses_directory_abstract_summary(wiki_structure: WikiStructure) -> None:
    abstract_path, _ = wiki_structure.get_directory_sidecar_paths("", create=True)
    abstract_path.write_text("Sidecar abstract summary for index.\n", encoding="utf-8")

    concept_path = wiki_structure.get_concept_file_path("alpha-topic")
    concept_path.write_text(
        "---\ntype: concept\n---\n# Alpha Topic\nBody first line should not win.\n",
        encoding="utf-8",
    )

    service = WikiCognitiveMapService(wiki_structure)
    service.refresh(WikiMapEvent(event_type=WikiMapEventType.COMPILE, summary="Index abstract test"))

    index_text = wiki_structure.get_index_file_path().read_text(encoding="utf-8")
    assert "Sidecar abstract summary for index." in index_text
    assert "Body first line should not win." not in index_text


def test_log_prepends_newest_entry(wiki_structure: WikiStructure) -> None:
    service = WikiCognitiveMapService(wiki_structure)
    service.refresh(
        WikiMapEvent(event_type=WikiMapEventType.COMPILE, summary="First event"),
    )
    service.refresh(
        WikiMapEvent(event_type=WikiMapEventType.MAINTAIN, summary="Second event"),
    )
    log_text = wiki_structure.get_log_file_path().read_text(encoding="utf-8")
    first_idx = log_text.index("Second event")
    second_idx = log_text.index("First event")
    assert first_idx < second_idx
