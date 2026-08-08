"""Tests for compile structure survey (AutoWiki-style pass 1)."""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.queue import WikiIngestionQueue
from myrm_agent_harness.toolkits.wiki.pipeline.survey import build_compile_survey
from myrm_agent_harness.toolkits.wiki.pipeline.survey.types import (
    FAST_PATH_MAX_RAW_COUNT,
)


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


def _raw_path(structure: WikiStructure, relative: str) -> Path:
    path = structure.base_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_empty_paths_skipped(wiki_structure: WikiStructure) -> None:
    context = build_compile_survey(wiki_structure, [])
    assert context.skipped is True
    assert context.facet_count == 0
    assert context.processing_order == ()


def test_fast_path_small_shallow_vault(wiki_structure: WikiStructure) -> None:
    paths = [
        _raw_path(wiki_structure, f"raw/doc-{index:02d}.md")
        for index in range(FAST_PATH_MAX_RAW_COUNT)
    ]
    context = build_compile_survey(wiki_structure, paths)
    assert context.skipped is True
    assert context.facet_count == 0


def test_fast_path_uses_vault_scope_not_pending_only(wiki_structure: WikiStructure) -> None:
    vault_paths = [
        _raw_path(wiki_structure, f"raw/doc-{index:02d}.md")
        for index in range(FAST_PATH_MAX_RAW_COUNT + 1)
    ]
    pending_only = vault_paths[:3]
    context = build_compile_survey(
        wiki_structure,
        pending_only,
        fast_path_scope_paths=vault_paths,
    )
    assert context.skipped is False
    assert context.facet_count >= 1


def test_survey_when_exceeds_fast_path_count(wiki_structure: WikiStructure) -> None:
    paths = [
        _raw_path(wiki_structure, f"raw/doc-{index:02d}.md")
        for index in range(FAST_PATH_MAX_RAW_COUNT + 1)
    ]
    context = build_compile_survey(wiki_structure, paths)
    assert context.skipped is False
    assert context.facet_count >= 1
    assert len(context.processing_order) >= 1


def test_survey_when_folder_depth_exceeds_fast_path(wiki_structure: WikiStructure) -> None:
    paths = [_raw_path(wiki_structure, "raw/deep/nested/doc.md")]
    context = build_compile_survey(wiki_structure, paths)
    assert context.skipped is False
    assert "raw/deep/nested" in context.facets


def test_chunk_sibling_grouping(wiki_structure: WikiStructure) -> None:
    paths = [
        _raw_path(wiki_structure, "raw/manual_chunk001.md"),
        _raw_path(wiki_structure, "raw/manual_chunk002.md"),
        _raw_path(wiki_structure, "raw/manual_chunk003.md"),
    ]
    # Force full survey via depth
    _raw_path(wiki_structure, "raw/deep/extra.md")
    context = build_compile_survey(wiki_structure, [*paths, wiki_structure.base_dir / "raw/deep/extra.md"])
    group_key = "raw/manual"
    assert group_key in context.chunk_groups
    assert len(context.chunk_groups[group_key]) == 3
    assert context.warning_count >= 1
    for rel in ("raw/manual_chunk001.md", "raw/manual_chunk002.md", "raw/manual_chunk003.md"):
        assert context.path_to_chunk_group[rel] == group_key


def test_facet_processing_order_by_depth(wiki_structure: WikiStructure) -> None:
    shallow = _raw_path(wiki_structure, "raw/shallow.md")
    deep = _raw_path(wiki_structure, "raw/projects/a/b/deep.md")
    context = build_compile_survey(wiki_structure, [shallow, deep])
    assert context.skipped is False
    assert context.processing_order[0] == "raw"
    assert context.processing_order[-1] == "raw/projects/a/b"


def test_queue_set_compile_phase_persists(wiki_structure: WikiStructure) -> None:
    queue = WikiIngestionQueue(wiki_structure)
    queue.set_compile_phase(
        "semantic_compile",
        facet_count=3,
        warning_count=1,
        survey_skipped=False,
    )
    snapshot = queue.get_compile_run()
    assert snapshot.phase == "semantic_compile"
    assert snapshot.facet_count == 3
    assert snapshot.warning_count == 1
    assert snapshot.survey_skipped is False

    queue.set_compile_phase("idle")
    idle_snapshot = queue.get_compile_run()
    assert idle_snapshot.phase == "idle"


def test_maybe_clear_session_keeps_state_when_pending(wiki_structure: WikiStructure) -> None:
    from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler

    queue = WikiIngestionQueue(wiki_structure)
    queue.add_item(str(wiki_structure.base_dir / "raw" / "pending.md"))
    compiler = WikiCompiler.__new__(WikiCompiler)
    compiler._structure = wiki_structure
    compiler._queue = queue
    compiler._ensure_compile_session()
    session_key = str(wiki_structure.base_dir)
    assert session_key in WikiCompiler._compile_sessions

    compiler._maybe_clear_compile_session()
    assert session_key in WikiCompiler._compile_sessions

    compiler._clear_compile_session()
    WikiCompiler._compile_sessions.pop(session_key, None)
