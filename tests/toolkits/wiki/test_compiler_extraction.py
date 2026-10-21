"""The concept extraction stage of a compile: survey blocks of the prompt, extraction order, missing sources."""

import asyncio
import os
import subprocess
import sys
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


def test_a_concept_keeps_its_sources_in_the_order_they_were_first_seen_under_any_hash_seed() -> None:
    # ``set`` order depends on PYTHONHASHSEED, so a merge through it writes the sources of a concept in a
    # different order in every process: the article's fallback claims and frontmatter differ for identical input.
    script = """
import sys

from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.compiler_extraction import merge_concept_sources

first = ConceptInfo(
    name="Pricing",
    definition="d",
    mentions=1,
    source_files=["raw/chats/turn_02.md", "raw/notes/policy-v2.md"],
)
second = ConceptInfo(
    name="Pricing",
    definition="d",
    mentions=1,
    source_files=["raw/chats/turn_01.md", "raw/notes/glossary.md"],
)
merged = merge_concept_sources(first, second)
sys.stdout.write(",".join(merged.source_files))
"""
    orders = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("1", "2", "3", "4")
    }

    assert orders == {"raw/chats/turn_02.md,raw/notes/policy-v2.md,raw/chats/turn_01.md,raw/notes/glossary.md"}


@pytest.mark.asyncio
async def test_a_cancelled_source_does_not_fail_its_batch_or_leave_its_row_processing(
    structure: WikiStructure,
) -> None:
    for name in ("good", "cut"):
        (structure.raw_dir / f"{name}.md").write_text(f"{name} text", encoding="utf-8")
    queue = WikiIngestionQueue(structure)
    queue.add_batch(sorted(structure.raw_dir.glob("*.md")))

    async def extract_doc(path: Path) -> list[ConceptInfo]:
        if path.name == "cut.md":
            raise asyncio.CancelledError
        return [ConceptInfo(name="Good", definition="d", source_files=["raw/good.md"])]

    outcome = await extract_concepts_batch(
        queue.get_pending_items(limit=10),
        queue=queue,
        structure=structure,
        get_session=lambda: None,
        semaphore=asyncio.Semaphore(2),
        extract_doc=extract_doc,
    )

    # A cancel is somebody stopping the compile, not a document the model refused: no failure to report, no
    # pause a batch of cancels could trigger, and no row left ``processing`` for the next open to recover.
    assert outcome.success_count == 1
    assert outcome.failure_kinds == []
    with queue._get_conn() as conn:
        rows = {
            Path(str(row["file_path"])).name: row["status"]
            for row in conn.execute("SELECT file_path, status FROM ingestion_queue")
        }
    assert rows == {"good.md": "processing", "cut.md": "pending"}


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [True, False])
async def test_a_genuine_stop_of_the_compile_still_reaches_the_caller(structure: WikiStructure, parallel: bool) -> None:
    """A source that raises ``CancelledError`` on its own must be absorbed; a stop aimed at the batch must not.

    ``asyncio.gather(..., return_exceptions=True)`` hands a cancelled child back as a *value*, so the helper has to
    tell the two apart: with ``parallel_compilation`` off there is no gather, and swallowing the caller's stop would
    turn a ``wait_for`` timeout or a ``task.cancel()`` into a batch that runs to completion anyway.
    """
    (structure.raw_dir / "slow.md").write_text("slow text", encoding="utf-8")
    queue = WikiIngestionQueue(structure)
    queue.add_batch(sorted(structure.raw_dir.glob("*.md")))

    async def extract_doc(path: Path) -> list[ConceptInfo]:
        await asyncio.sleep(30)
        return [ConceptInfo(name="Good", definition="d", source_files=["raw/slow.md"])]

    async def run_batch() -> list[ConceptInfo]:
        return await extract_concepts_batch(
            queue.get_pending_items(limit=10),
            queue=queue,
            structure=structure,
            get_session=lambda: None,
            semaphore=asyncio.Semaphore(2) if parallel else None,
            extract_doc=extract_doc,
        )

    task = asyncio.create_task(run_batch())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(task), timeout=5)

    # The stop reached the caller, and the row it was working on is queued again rather than left ``processing``.
    with queue._get_conn() as conn:
        rows = {
            Path(str(row["file_path"])).name: row["status"]
            for row in conn.execute("SELECT file_path, status FROM ingestion_queue")
        }
    assert rows == {"slow.md": "pending"}
