"""Writing the wiki articles of a batch's concepts: what was written, what failed and why."""

import asyncio

import pytest

from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedInputTooLargeError
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.articles import generate_articles_batch
from myrm_agent_harness.toolkits.wiki.pipeline.resilience import EMBED_WINDOW_VIOLATION


def _concept(name: str, *sources: str, mentions: int = 2) -> ConceptInfo:
    return ConceptInfo(name=name, definition="d", mentions=mentions, source_files=list(sources) or ["a.md"])


def _semaphore(parallel: bool) -> asyncio.Semaphore | None:
    return asyncio.Semaphore(2) if parallel else None


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [True, False])
async def test_the_batch_counts_what_was_published_staged_and_blocked(parallel: bool) -> None:
    outcomes = {"p": "published", "q": "pending", "r": "blocked"}

    async def generate(concept: ConceptInfo) -> str:
        return outcomes[concept.name]

    stats = await generate_articles_batch(
        [_concept("p"), _concept("q"), _concept("r")], generate, min_mentions=1, semaphore=_semaphore(parallel)
    )

    assert (stats.generated, stats.published, stats.pending, stats.blocked) == (2, 1, 1, 1)
    assert stats.failures == ()


@pytest.mark.asyncio
async def test_concepts_below_the_mention_threshold_get_no_article() -> None:
    written: list[str] = []

    async def generate(concept: ConceptInfo) -> str:
        written.append(concept.name)
        return "published"

    stats = await generate_articles_batch(
        [_concept("seen", mentions=2), _concept("rare", mentions=1)], generate, min_mentions=2, semaphore=None
    )

    assert written == ["seen"]
    assert stats.generated == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [True, False])
async def test_a_failed_article_is_recorded_with_its_sources_and_classification_in_concept_order(
    parallel: bool,
) -> None:
    async def generate(concept: ConceptInfo) -> str:
        if concept.name == "slow":
            await asyncio.sleep(0.05)
        if concept.name in {"slow", "fast"}:
            raise RuntimeError("429 rate limit exceeded")
        return "published"

    stats = await generate_articles_batch(
        [_concept("slow", "a.md", "b.md"), _concept("fine", "c.md"), _concept("fast", "d.md")],
        generate,
        min_mentions=1,
        semaphore=_semaphore(parallel),
    )

    assert [(f.name, f.source_files, f.resolution.error_kind) for f in stats.failures] == [
        ("slow", ("a.md", "b.md"), ErrorKind.RATE_LIMIT.value),
        ("fast", ("d.md",), ErrorKind.RATE_LIMIT.value),
    ]
    assert stats.failures[0].resolution.retry_after_seconds == 120
    assert (stats.generated, stats.blocked) == (1, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [True, False])
async def test_an_embed_window_violation_pauses_the_compile_and_is_not_a_failed_article(parallel: bool) -> None:
    async def generate(concept: ConceptInfo) -> str:
        raise EmbedInputTooLargeError(token_count=900, limit=512, model="test-embed", parent_key=concept.name)

    stats = await generate_articles_batch([_concept("big")], generate, min_mentions=1, semaphore=_semaphore(parallel))

    assert stats.embed_pause_kind == EMBED_WINDOW_VIOLATION
    assert "900" in stats.embed_pause_reason
    # The article is on disk and only its vector index is missing, so the source behind it is not failed.
    assert stats.failures == ()
    assert stats.blocked == 1


@pytest.mark.asyncio
async def test_an_article_task_that_was_cancelled_is_a_failed_article_not_a_lost_one() -> None:
    async def generate(concept: ConceptInfo) -> str:
        if concept.name == "cut":
            raise asyncio.CancelledError
        return "published"

    stats = await generate_articles_batch(
        [_concept("cut", "a.md"), _concept("fine", "b.md")], generate, min_mentions=1, semaphore=_semaphore(True)
    )

    assert [(f.name, f.source_files) for f in stats.failures] == [("cut", ("a.md",))]
    assert (stats.generated, stats.blocked) == (1, 1)
