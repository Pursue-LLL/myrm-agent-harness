"""Wiki article generation: one article per concept, a batch at a time.

[INPUT]
- langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
- toolkits.retriever.embedding.window_policy::EmbedInputTooLargeError (POS: embed window violation)
- ..core.claims_contract::ensure_compile_claims (POS: claims block of a compiled article)
- ..core.config::WikiCompileConfig (POS: compile prompts and limits)
- ..core.frontmatter_contract::WikiProvenance, apply_compile_gate, serialize_frontmatter_block (POS: frontmatter gate)
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
- ..core.types::ConceptInfo (POS: Wiki toolkit type definitions)
- .article_evidence::build_source_evidence, source_budget_chars (POS: the numbered source text an article is written from)
- .compiler_provenance::provenance_from_raw_sources, restore_provenance_metadata (POS: provenance preservation)
- .pending::WikiPendingEditsManager (POS: drafts awaiting approval)
- .publication::ArticlePublishOutcome, publish_concept_article (POS: validated publish plus search index upsert)
- .resilience::FailureResolution, reraise_if_cancelled, resolve_blocked_publish, resolve_embed_failure, resolve_llm_failure (POS: failure classification)
- utils.chat_utils::extract_answer_text (POS: LLM answer extraction)

[OUTPUT]
- ArticleBlockedError: the publish content scan refused an article, so nothing was written
- ConceptFailure: a concept whose article could not be written, with the sources behind it and why
- ArticleBatchStats: what a batch wrote, what it could not, and the embed pause an index failure asks for
- generate_article: write (or stage for approval) the article of one concept
- generate_articles_batch: write the articles of a batch's concepts with bounded concurrency

[POS]
The article stage of a compile. It reports failures per concept, with the sources the concept came from, so the
compiler can fail exactly the sources whose results are incomplete instead of completing them without an article.
A cancelled task is not such a failure: somebody stopped the compile, so its concept is left out of the batch's
failures and the sources behind it are neither failed nor completed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedInputTooLargeError
from myrm_agent_harness.toolkits.wiki.core.claims_contract import ensure_compile_claims
from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    WikiProvenance,
    apply_compile_gate,
    serialize_frontmatter_block,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.utils.chat_utils import extract_answer_text
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .article_evidence import build_source_evidence, source_budget_chars
from .compiler_provenance import provenance_from_raw_sources, restore_provenance_metadata
from .pending import WikiPendingEditsManager
from .publication import ArticlePublishOutcome, publish_concept_article
from .resilience import (
    FailureResolution,
    reraise_if_cancelled,
    resolve_blocked_publish,
    resolve_embed_failure,
    resolve_llm_failure,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)

_PENDING = "pending"
_PUBLISHED = "published"
_EMBED_BLOCKED = "blocked"
# A concept whose article task was cancelled. The article generator never returns it from a real outcome; it exists
# so the positional results of a batch stay aligned with its concepts.
_STOPPED = "stopped"


class ArticleBlockedError(Exception):
    """The publish content scan refused an article, so nothing was written for its concept."""


@dataclass(frozen=True, slots=True)
class ConceptFailure:
    """A concept whose article could not be written."""

    name: str
    # Every source the concept was extracted from, as the compiler names them (the raw path relative to the vault).
    source_files: tuple[str, ...]
    resolution: FailureResolution


@dataclass(frozen=True, slots=True)
class ArticleBatchStats:
    generated: int
    pending: int
    published: int
    # Concepts that got no article: the ``failures`` plus those whose index entry hit the embed window.
    blocked: int
    embed_pause_reason: str = ""
    embed_pause_kind: str = ""
    # In the order of the batch's concepts. An embed window violation is not listed: the article is on disk and
    # only its vector index is missing, which the compile pause reports.
    failures: tuple[ConceptFailure, ...] = ()


def _failure_of(concept: ConceptInfo, error: Exception) -> ConceptFailure:
    return ConceptFailure(
        name=concept.name,
        source_files=tuple(concept.source_files),
        resolution=resolve_blocked_publish() if isinstance(error, ArticleBlockedError) else resolve_llm_failure(error),
    )


async def generate_articles_batch(
    concepts: list[ConceptInfo],
    generate: Callable[[ConceptInfo], Awaitable[str]],
    *,
    min_mentions: int,
    semaphore: asyncio.Semaphore | None,
) -> ArticleBatchStats:
    """Generate wiki articles with configurable parallelism.

    Args:
        concepts: The batch's concepts; those mentioned fewer than ``min_mentions`` times get no article.
        generate: Writes one concept's article and returns ``"published"`` or ``"pending"``, or raises.
        min_mentions: The mention threshold below which a concept is noise.
        semaphore: Bounds the concurrency; ``None`` generates the articles one after another.
    """
    filtered = [c for c in concepts if c.mentions >= min_mentions]
    logger.info(f"Generating articles for {len(filtered)} concepts")

    embed_pause: list[tuple[str, str]] = []
    stopped: list[str] = []

    async def _gen_one(concept: ConceptInfo) -> str | ConceptFailure:
        try:
            if semaphore:
                async with semaphore:
                    return await generate(concept)
            return await generate(concept)
        except EmbedInputTooLargeError as exc:
            if not embed_pause:
                embed_pause.append(resolve_embed_failure(exc))
            logger.error(
                "Embedding window violation while publishing wiki concept '%s': %s",
                concept.name,
                exc,
            )
            return _EMBED_BLOCKED
        except asyncio.CancelledError as exc:
            # Somebody stopped the compile, the concept was not refused: the indices stay aligned so the sources
            # behind it are neither failed nor completed, and a cancel is not a failure a pause is reported for.
            # A stop meant for this task is raised again, so it still reaches whoever asked for it.
            stopped.append(concept.name)
            reraise_if_cancelled(exc)
            return _STOPPED
        except Exception as e:
            logger.error(f"Failed to generate article for {concept.name}: {e}")
            return _failure_of(concept, e)

    if semaphore is not None:
        results = await asyncio.gather(
            *[_gen_one(c) for c in filtered],
            return_exceptions=True,
        )
    else:
        results = [await _gen_one(c) for c in filtered]

    pending = 0
    published = 0
    blocked = 0
    failures: list[ConceptFailure] = []
    for concept, result in zip(filtered, results, strict=True):
        if isinstance(result, BaseException):
            # A non-``Exception`` the generator leaked (``_gen_one`` handles every ``Exception`` and every cancel of
            # its own); a genuine stop is raised by ``_gen_one`` and travels through ``gather`` instead of landing
            # here. Classified like any other failure so one leaked ``BaseException`` cannot drop the batch.
            result = _failure_of(concept, RuntimeError(str(result)))
        if isinstance(result, ConceptFailure):
            failures.append(result)
            blocked += 1
        elif result == _PENDING:
            pending += 1
        elif result == _PUBLISHED:
            published += 1
        elif result != _STOPPED:
            blocked += 1

    if stopped:
        logger.info(f"{len(stopped)} article task(s) were stopped mid-batch; their sources stay for the next compile")

    return ArticleBatchStats(
        generated=pending + published,
        pending=pending,
        published=published,
        blocked=blocked,
        embed_pause_reason=embed_pause[0][0] if embed_pause else "",
        embed_pause_kind=embed_pause[0][1] if embed_pause else "",
        failures=tuple(failures),
    )


async def generate_article(
    llm: BaseChatModel,
    structure: WikiStructure,
    compile_config: WikiCompileConfig,
    indexer: WikiIndexer | None,
    concept: ConceptInfo,
) -> str:
    """Generate wiki article for a concept in Obsidian format.

    Returns:
        ``"pending"`` when the article was staged for approval, ``"published"`` when it was written and indexed.
    """
    article_path = structure.get_concept_file_path(concept.name)
    existing_content = ""
    if article_path.exists():
        existing_content = article_path.read_text(encoding="utf-8")

    purpose_context = ""
    purpose_path = structure.get_purpose_path()
    if purpose_path.exists():
        purpose_text = purpose_path.read_text(encoding="utf-8").strip()
        if purpose_text:
            purpose_context = f"Knowledge base direction: {purpose_text}\nFocus your article within this scope.\n\n"

    # Read and scored on a worker thread: a long source must not stall the event loop the other articles run on.
    source_docs = await asyncio.to_thread(
        build_source_evidence,
        structure,
        concept,
        source_budget_chars(llm, compile_config.max_source_context_chars),
    )
    prompt = compile_config.generate_article_prompt_template.format(
        concept_name=concept.name,
        purpose_context=purpose_context,
        source_docs=source_docs,
    )

    if existing_content:
        prompt += f"\n\n# Existing Wiki Content\nPlease update the Compiled Truth section using the new source documents, but MUST PRESERVE the existing Timeline and APPEND new evidence to the bottom of the Timeline:\n\n{existing_content}"

    system_msg = SystemMessage(content="You are a technical writer creating wiki articles.")
    human_msg = HumanMessage(content=prompt)

    response = await llm.ainvoke([system_msg, human_msg])
    article_content = extract_answer_text(response)

    if len(article_content) > compile_config.max_article_length:
        article_content = article_content[: compile_config.max_article_length] + "\n\n(truncated)"

    article_content = apply_compile_gate(
        article_content,
        concept.name,
        concept.source_files,
    )

    article_content = ensure_compile_claims(
        article_content,
        concept.name,
        list(concept.source_files),
        structure=structure,
    )

    restore_base = existing_content
    if not restore_base and concept.source_files:
        # First compile of a brand-new concept: raw sources (e.g. auto-archived
        # turns) carry source_chat provenance that would otherwise be lost.
        source_provenance = provenance_from_raw_sources(structure, list(concept.source_files))
        if source_provenance:
            restore_base = serialize_frontmatter_block(dict[str, object](source_provenance))

    article_content = restore_provenance_metadata(restore_base, article_content)

    if compile_config.require_approval:
        pending_mgr = WikiPendingEditsManager(structure, indexer)
        await pending_mgr.stage_pending_edit(
            concept.name,
            article_content,
            source_files=concept.source_files,
            provenance=WikiProvenance.COMPILED,
        )
        logger.info(f"Generated pending draft for article: {concept.name}")
        return _PENDING

    outcome = await publish_concept_article(
        structure,
        indexer,
        concept.name,
        article_content,
    )
    if outcome is ArticlePublishOutcome.BLOCKED:
        raise ArticleBlockedError(f"Article of '{concept.name}' was refused by the publish content scan")
    logger.info(f"Generated and published article: {concept.name}")
    return _PUBLISHED
