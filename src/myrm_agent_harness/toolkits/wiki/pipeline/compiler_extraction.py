"""Concept extraction stage of a wiki compile: read the sources of a batch and ask the model for their concepts.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
- ..core.config::WikiCompileConfig (POS: compile prompts and limits)
- ..core.parsers::parse_concepts_response (POS: LLM response parser)
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
- ..core.types::ConceptInfo (POS: Wiki toolkit type definitions)
- .batch_settle::source_hash (POS: the file hash the batch settles against)
- .cognitive_map.schema_writer::read_index_context (POS: the wiki catalog a concept name is reused from)
- .queue::QueueItem, WikiIngestionQueue (POS: persistent ingestion queue)
- .resilience::IO_MISSING, reraise_if_cancelled, resolve_llm_failure (POS: failure classification)
- .survey::CompileSessionState (POS: survey state shared across the batches of one compile)
- utils.chat_utils::extract_answer_text (POS: LLM answer extraction)

[OUTPUT]
- BatchExtractOutcome: the concepts of a batch, the sources that were read and the failures that were not
- relative_raw_path: the vault-relative path the prompts and the queue refer to a source by
- merge_concept_sources: one concept as several sources of a batch described it, each list in first-seen order
- build_extract_survey_context: the survey blocks (facet, concept seeds, chunk group) the extraction prompt carries
- record_facet_seeds: carry the concepts of a batch forward as seeds for the next batches of the same facet
- extract_concepts_from_doc: ask the model for the concepts of one document
- extract_concepts_batch: extract the concepts of a batch's sources, merging a concept several sources mention

[POS]
The extraction half of a compile batch. A source that fails here is marked failed in the queue at once; a source
that succeeds stays ``processing`` (with the hash of the file as extraction read it) until the batch has written
the rest of its results, which ``batch_settle`` decides. A task that was cancelled is queued again instead: the
compile was stopped, not the source refused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig
from myrm_agent_harness.toolkits.wiki.core.parsers import parse_concepts_response
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.utils.chat_utils import extract_answer_text
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .batch_settle import source_hash
from .cognitive_map.schema_writer import read_index_context
from .queue import QueueItem, WikiIngestionQueue
from .resilience import IO_MISSING, reraise_if_cancelled, resolve_llm_failure
from .survey import CompileSessionState

logger = get_agent_logger(__name__)

_MAX_FACET_SEEDS = 12
_MAX_CHUNK_GROUP_PATHS = 20


@dataclass(frozen=True, slots=True)
class BatchExtractOutcome:
    concepts: list[ConceptInfo]
    # Sources whose concepts were extracted, each with its file's hash from before extraction read it. They stay
    # ``processing`` until the batch has written the rest of their results; only the failures are settled during
    # extraction.
    read_hashes: dict[int, str | None]
    failure_kinds: list[str]

    @property
    def success_count(self) -> int:
        return len(self.read_hashes)


def relative_raw_path(structure: WikiStructure, doc_path: Path) -> str:
    try:
        return doc_path.relative_to(structure.base_dir).as_posix()
    except ValueError:
        return doc_path.name


def merge_concept_sources(existing: ConceptInfo, concept: ConceptInfo) -> ConceptInfo:
    """One concept, as a batch extracted it from several sources.

    Sources and related concepts keep the order they were first seen in. Merging them through a ``set`` would
    order them by ``PYTHONHASHSEED``, so the same vault compiles into different article frontmatter and claims
    in every process.
    """
    return ConceptInfo(
        name=concept.name,
        definition=concept.definition,
        mentions=existing.mentions + concept.mentions,
        source_files=list(dict.fromkeys([*existing.source_files, *concept.source_files])),
        related_concepts=list(dict.fromkeys([*existing.related_concepts, *concept.related_concepts])),
    )


def _sort_for_survey(
    session: CompileSessionState | None, structure: WikiStructure, queue_items: list[QueueItem]
) -> list[QueueItem]:
    if session is None or session.context.skipped:
        return queue_items

    order_index = {facet_id: index for index, facet_id in enumerate(session.context.processing_order)}

    def _sort_key(item: QueueItem) -> tuple[int, str]:
        rel = relative_raw_path(structure, Path(str(item["file_path"])))
        facet_id = session.context.path_to_facet.get(rel, "")
        return (order_index.get(facet_id, len(order_index)), rel)

    return sorted(queue_items, key=_sort_key)


def build_extract_survey_context(session: CompileSessionState | None, relative_path: str) -> str:
    if session is None or session.context.skipped:
        return ""

    sections: list[str] = []
    facet_id = session.context.path_to_facet.get(relative_path)
    if facet_id is not None:
        facet = session.context.facets.get(facet_id)
        if facet is not None:
            sections.append(f"# Compile Facet: {facet.folder_path}")
            seed_lines = [
                *session.facet_seeds.get(facet_id, []),
                *list(facet.suggested_seeds),
            ]
            unique_seeds = list(dict.fromkeys(seed for seed in seed_lines if seed))[:_MAX_FACET_SEEDS]
            if unique_seeds:
                sections.append(
                    "# Facet concept seeds (reuse these names when applicable):\n"
                    + "\n".join(f"- {seed}" for seed in unique_seeds)
                )

    chunk_group_id = session.context.path_to_chunk_group.get(relative_path)
    if chunk_group_id is not None:
        siblings = session.context.chunk_groups.get(chunk_group_id, ())
        if len(siblings) > 1:
            sections.append(
                f"# Chunk group ({len(siblings)} parts of one source document)\n"
                "Extract concepts once for the whole group; prefer one shared concept path.\n"
                + "\n".join(f"- {path}" for path in siblings[:_MAX_CHUNK_GROUP_PATHS])
            )

    if not sections:
        return ""
    return "\n\n".join(sections) + "\n\n"


def record_facet_seeds(
    session: CompileSessionState | None,
    structure: WikiStructure,
    queue_items: Sequence[QueueItem],
    concepts: Sequence[ConceptInfo],
) -> None:
    if session is None or session.context.skipped or not concepts:
        return

    batch_paths = {relative_raw_path(structure, Path(str(item["file_path"]))) for item in queue_items}
    for concept in concepts:
        for source in concept.source_files:
            if source not in batch_paths:
                continue
            facet_id = session.context.path_to_facet.get(source)
            if facet_id is None:
                continue
            seeds = session.facet_seeds.setdefault(facet_id, [])
            if concept.name not in seeds:
                seeds.append(concept.name)


async def extract_concepts_from_doc(
    llm: BaseChatModel,
    structure: WikiStructure,
    compile_config: WikiCompileConfig,
    session: CompileSessionState | None,
    doc_path: Path,
) -> list[ConceptInfo]:
    """Extract concepts from a single document using LLM, with path as context."""
    try:
        content = doc_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read {doc_path}: {e}")
        return []

    # Include relative path as context (e.g. docs/architecture.md vs notes/daily.md)
    relative_path = relative_raw_path(structure, doc_path)

    survey_context = build_extract_survey_context(session, relative_path)
    index_context = read_index_context(structure)
    index_block = ""
    if index_context:
        index_block = f"# Existing wiki catalog (reuse these concept names when applicable):\n{index_context}\n\n"
    prompt = compile_config.extract_concepts_prompt_template
    system_msg = SystemMessage(content="You are a knowledge extraction expert.")
    human_msg = HumanMessage(
        content=(
            f"{prompt}\n\n{survey_context}{index_block}# Document Path: {relative_path}\n# Document Content:\n\n{content}"
        )
    )

    try:
        response = await llm.ainvoke([system_msg, human_msg])
        response_text = extract_answer_text(response).strip()
        logger.info(f"LLM extraction response for {doc_path}: {response_text}")
        concepts = parse_concepts_response(response_text, str(relative_path))
        return concepts
    except Exception as e:
        logger.error(f"LLM extraction failed for {doc_path}: {e}")
        raise


async def extract_concepts_batch(
    queue_items: list[QueueItem],
    *,
    queue: WikiIngestionQueue,
    structure: WikiStructure,
    get_session: Callable[[], CompileSessionState | None],
    semaphore: asyncio.Semaphore | None,
    extract_doc: Callable[[Path], Awaitable[list[ConceptInfo]]],
) -> BatchExtractOutcome:
    """Extract concepts from queue items: concurrently, bounded by ``semaphore``, when there is one; else one by one."""
    queue_items = _sort_for_survey(get_session(), structure, queue_items)
    failure_kinds: list[str] = []
    read_hashes: dict[int, str | None] = {}
    stopped: list[int] = []

    async def _process_single_item(item: QueueItem) -> list[ConceptInfo]:
        item_id = item["id"]
        raw_file = Path(item["file_path"])
        queue.mark_processing(item_id)
        try:
            if not raw_file.exists():
                queue.mark_failed(item_id, "File not found", error_kind=IO_MISSING)
                return []
            # Hashed before the read: an edit after this point is caught when the batch settles.
            digest = source_hash(raw_file)
            if semaphore:
                async with semaphore:
                    concepts = await extract_doc(raw_file)
            else:
                concepts = await extract_doc(raw_file)
            if not concepts:
                resolution = resolve_llm_failure(RuntimeError("Concept extraction returned no concepts"))
                queue.mark_failed(
                    item_id,
                    "Concept extraction returned no concepts",
                    error_kind=resolution.error_kind,
                    retry_after_seconds=resolution.retry_after_seconds,
                )
                failure_kinds.append(resolution.error_kind)
                return []
            read_hashes[item_id] = digest
            return concepts
        except asyncio.CancelledError as exc:
            # Somebody stopped the compile, the source was not refused: queue it again instead of failing a
            # document, and do not count it as a failure a compile pause would be reported for. A stop meant for
            # this task is raised again, so it still reaches whoever asked for it.
            queue.requeue_processing([item_id])
            stopped.append(item_id)
            reraise_if_cancelled(exc)
            return []
        except Exception as e:
            logger.error(f"Failed to extract concepts from {raw_file}: {e}")
            resolution = resolve_llm_failure(e)
            queue.mark_failed(
                item_id,
                str(e),
                error_kind=resolution.error_kind,
                retry_after_seconds=resolution.retry_after_seconds,
            )
            failure_kinds.append(resolution.error_kind)
            return []

    if semaphore:
        results = await asyncio.gather(
            *[_process_single_item(item) for item in queue_items],
            return_exceptions=True,
        )
    else:
        results = [await _process_single_item(item) for item in queue_items]

    all_concepts: dict[str, ConceptInfo] = {}
    for result in results:
        if isinstance(result, BaseException):
            logger.error(f"Unexpected error in concept extraction: {result}")
            resolution = resolve_llm_failure(result if isinstance(result, Exception) else RuntimeError(str(result)))
            failure_kinds.append(resolution.error_kind)
            continue
        for concept in result:
            if concept.name in all_concepts:
                all_concepts[concept.name] = merge_concept_sources(all_concepts[concept.name], concept)
            else:
                all_concepts[concept.name] = concept

    if stopped:
        logger.info(f"{len(stopped)} source(s) were stopped mid-extraction; queued again")

    record_facet_seeds(get_session(), structure, queue_items, list(all_concepts.values()))

    return BatchExtractOutcome(
        concepts=list(all_concepts.values()),
        read_hashes=read_hashes,
        failure_kinds=failure_kinds,
    )
