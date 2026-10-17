"""The concept extraction stage of a compile: survey blocks of the prompt, extraction order, missing sources."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler
from myrm_agent_harness.toolkits.wiki.pipeline.compiler_extraction import (
    build_extract_survey_context,
    extract_concepts_batch,
    relative_raw_path,
)
from myrm_agent_harness.toolkits.wiki.pipeline.queue import WikiIngestionQueue
from myrm_agent_harness.toolkits.wiki.pipeline.resilience import IO_MISSING
from myrm_agent_harness.toolkits.wiki.pipeline.survey import CompileSessionState, CompileSurveyContext, FacetSurvey
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    wiki = WikiStructure(tmp_path)
    wiki.ensure_structure()
    return wiki


@pytest.fixture
def indexer() -> AsyncMock:
    mock = AsyncMock(spec=WikiIndexer)
    mock.extract_and_upsert_edges = MagicMock()
    return mock


def _session(
    *,
    facets: dict[str, FacetSurvey] | None = None,
    chunk_groups: dict[str, tuple[str, ...]] | None = None,
    path_to_facet: dict[str, str] | None = None,
    path_to_chunk_group: dict[str, str] | None = None,
    processing_order: tuple[str, ...] = (),
    skipped: bool = False,
    facet_seeds: dict[str, list[str]] | None = None,
) -> CompileSessionState:
    context = CompileSurveyContext(
        skipped=skipped,
        facet_count=len(facets or {}),
        warning_count=0,
        facets=facets or {},
        chunk_groups=chunk_groups or {},
        path_to_facet=path_to_facet or {},
        path_to_chunk_group=path_to_chunk_group or {},
        processing_order=processing_order,
        warnings=(),
    )
    return CompileSessionState(context=context, facet_seeds=facet_seeds or {})


def _facet(facet_id: str, suggested_seeds: tuple[str, ...] = ()) -> FacetSurvey:
    return FacetSurvey(
        facet_id=facet_id, folder_path=f"raw/{facet_id}", raw_paths=(), suggested_seeds=suggested_seeds, depth=1
    )


def test_a_source_is_named_by_its_path_in_the_vault_and_one_outside_it_by_its_file_name(
    structure: WikiStructure,
) -> None:
    assert relative_raw_path(structure, structure.raw_dir / "docs" / "a.md") == "raw/docs/a.md"
    assert relative_raw_path(structure, structure.base_dir.parent / "elsewhere" / "b.md") == "b.md"


def test_the_prompt_carries_at_most_twelve_seeds_those_of_earlier_batches_first_without_repeats() -> None:
    earlier = [f"earlier-{index}" for index in range(10)]
    session = _session(
        facets={"docs": _facet("docs", ("earlier-0", "suggested-0", "suggested-1", "suggested-2", "suggested-3"))},
        path_to_facet={"raw/docs/a.md": "docs"},
        facet_seeds={"docs": earlier},
    )

    block = build_extract_survey_context(session, "raw/docs/a.md")

    seeds = [line.removeprefix("- ") for line in block.splitlines() if line.startswith("- ")]
    assert seeds == [*earlier, "suggested-0", "suggested-1"]
    assert block.startswith("# Compile Facet: raw/docs\n\n# Facet concept seeds")
    assert block.endswith("\n\n")


def test_the_prompt_lists_at_most_twenty_parts_of_a_chunk_group() -> None:
    parts = tuple(f"raw/book/part{index:02d}.md" for index in range(25))
    session = _session(chunk_groups={"book": parts}, path_to_chunk_group={parts[3]: "book"})

    block = build_extract_survey_context(session, parts[3])

    assert "# Chunk group (25 parts of one source document)" in block
    assert [line for line in block.splitlines() if line.startswith("- ")] == [f"- {part}" for part in parts[:20]]


def test_a_source_alone_in_its_chunk_group_adds_no_block() -> None:
    session = _session(chunk_groups={"solo": ("raw/solo.md",)}, path_to_chunk_group={"raw/solo.md": "solo"})

    assert build_extract_survey_context(session, "raw/solo.md") == ""


def test_there_is_no_survey_block_without_a_session_or_when_the_survey_was_skipped() -> None:
    skipped = _session(
        facets={"docs": _facet("docs", ("seed",))}, path_to_facet={"raw/docs/a.md": "docs"}, skipped=True
    )

    assert build_extract_survey_context(None, "raw/docs/a.md") == ""
    assert build_extract_survey_context(skipped, "raw/docs/a.md") == ""


@pytest.mark.asyncio
async def test_the_sources_of_a_batch_are_read_in_the_order_of_the_survey_not_the_order_they_were_queued(
    structure: WikiStructure,
) -> None:
    paths = {
        name: structure.raw_dir / folder / f"{name}.md"
        for name, folder in (("alpha", "a"), ("beta", "a"), ("zeta", "b"))
    }
    queue = WikiIngestionQueue(structure)
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{path.stem} text", encoding="utf-8")
        queue.add_item(path)
    session = _session(
        path_to_facet={"raw/a/alpha.md": "a", "raw/a/beta.md": "a", "raw/b/zeta.md": "b"},
        processing_order=("b", "a"),
    )
    read: list[str] = []

    async def extract_doc(path: Path) -> list[ConceptInfo]:
        read.append(path.stem)
        return [ConceptInfo(name=path.stem, definition="d", source_files=[f"raw/{path.parent.name}/{path.name}"])]

    outcome = await extract_concepts_batch(
        queue.get_pending_items(limit=10),
        queue=queue,
        structure=structure,
        get_session=lambda: session,
        semaphore=None,
        extract_doc=extract_doc,
    )

    assert read == ["zeta", "alpha", "beta"]
    assert outcome.success_count == 3
    assert session.facet_seeds == {"b": ["zeta"], "a": ["alpha", "beta"]}


@pytest.mark.asyncio
async def test_a_queued_source_whose_file_is_gone_fails_as_missing_and_does_not_count_toward_a_pause(
    structure: WikiStructure,
) -> None:
    queue = WikiIngestionQueue(structure)
    queue.add_item(structure.raw_dir / "gone.md")
    extract_doc = AsyncMock(return_value=[])

    outcome = await extract_concepts_batch(
        queue.get_pending_items(limit=10),
        queue=queue,
        structure=structure,
        get_session=lambda: None,
        semaphore=None,
        extract_doc=extract_doc,
    )

    extract_doc.assert_not_called()
    assert outcome.success_count == 0
    assert outcome.failure_kinds == []
    [failed] = queue.get_failed_items(limit=5)
    assert failed["error_kind"] == IO_MISSING
    assert failed["error_message"] == "File not found"


@pytest.mark.asyncio
async def test_a_batch_that_read_one_source_does_not_pause_the_compile_for_the_transient_failures_of_the_others(
    structure: WikiStructure, indexer: AsyncMock
) -> None:
    for name in ("good", "slow-1", "slow-2", "slow-3"):
        (structure.raw_dir / f"{name}.md").write_text(f"{name} text", encoding="utf-8")

    async def answer(messages: list[object]) -> AIMessage:
        prompt = str(getattr(messages[-1], "content", ""))
        if "# Document Content:" not in prompt:
            return AIMessage(content="## Compiled Truth\nArticle.")
        if "slow-" in prompt:
            raise RuntimeError("429 rate limit exceeded")
        return AIMessage(content='[{"name": "Good", "definition": "d"}]')

    llm = AsyncMock()
    llm.ainvoke.side_effect = answer
    compiler = WikiCompiler(llm, structure, WikiConfig(parallel_compilation=False), indexer=indexer)

    await compiler.compile_all()

    assert not compiler._queue.is_compile_paused()


@pytest.mark.asyncio
async def test_the_map_the_compile_refreshes_counts_the_sources_still_waiting_in_the_queue(
    structure: WikiStructure,
) -> None:
    compiler = WikiCompiler(AsyncMock(), structure, WikiConfig())
    for name in ("one", "two"):
        path = structure.raw_dir / f"{name}.md"
        path.write_text(f"{name} text", encoding="utf-8")
        compiler._queue.add_item(path)

    compiler._refresh_cognitive_map([], summary="refresh")

    assert "Ingestion queue: 2 file(s) pending compilation" in structure.get_hot_file_path().read_text(encoding="utf-8")
