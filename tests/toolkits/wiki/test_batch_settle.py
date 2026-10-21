"""What a compile batch's sources become once the batch is done: completed, queued again, or failed."""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.articles import ConceptFailure
from myrm_agent_harness.toolkits.wiki.pipeline.batch_settle import (
    blocked_sources,
    fail_extracted,
    settle_extracted,
    source_hash,
)
from myrm_agent_harness.toolkits.wiki.pipeline.queue import QueueItem, WikiIngestionQueue
from myrm_agent_harness.toolkits.wiki.pipeline.resilience import FailureResolution, resolve_llm_failure


@pytest.fixture
def queue(tmp_path: Path) -> WikiIngestionQueue:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return WikiIngestionQueue(structure)


def _processing_batch(queue: WikiIngestionQueue, *paths: Path) -> list[QueueItem]:
    queue.add_batch(list(paths))
    items = queue.get_pending_items()
    for item in items:
        queue.mark_processing(item["id"])
    return items


def _ids_by_name(items: list[QueueItem]) -> dict[str, int]:
    return {Path(item["file_path"]).name: item["id"] for item in items}


def test_source_hash_is_none_for_a_file_that_cannot_be_read(tmp_path: Path) -> None:
    present = tmp_path / "present.md"
    present.write_text("content")

    assert source_hash(present) is not None
    assert source_hash(tmp_path / "missing.md") is None


def test_sources_whose_files_are_as_extraction_read_them_are_completed(
    queue: WikiIngestionQueue, tmp_path: Path
) -> None:
    unchanged = tmp_path / "unchanged.md"
    unchanged.write_text("same")
    items = _processing_batch(queue, unchanged)

    settle_extracted(queue, items, {items[0]["id"]: source_hash(unchanged)}, {})

    assert queue.get_stats() == {"pending": 0, "processing": 0, "completed": 1, "failed": 0}


def test_a_source_edited_while_its_batch_ran_is_queued_again_and_the_others_are_completed(
    queue: WikiIngestionQueue, tmp_path: Path
) -> None:
    edited, unchanged = tmp_path / "edited.md", tmp_path / "unchanged.md"
    edited.write_text("version one")
    unchanged.write_text("same")
    items = _processing_batch(queue, edited, unchanged)
    ids = _ids_by_name(items)
    read = {ids["edited.md"]: source_hash(edited), ids["unchanged.md"]: source_hash(unchanged)}
    edited.write_text("version two")

    settle_extracted(queue, items, read, {})

    assert queue.get_stats() == {"pending": 1, "processing": 0, "completed": 1, "failed": 0}
    assert [item["id"] for item in queue.get_pending_items()] == [ids["edited.md"]]


def test_a_source_that_vanished_while_its_batch_ran_is_completed(queue: WikiIngestionQueue, tmp_path: Path) -> None:
    vanished = tmp_path / "vanished.md"
    vanished.write_text("content")
    items = _processing_batch(queue, vanished)
    read = {items[0]["id"]: source_hash(vanished)}
    vanished.unlink()

    settle_extracted(queue, items, read, {})

    assert queue.get_stats() == {"pending": 0, "processing": 0, "completed": 1, "failed": 0}


def test_a_source_that_could_not_be_read_before_extraction_but_can_be_now_is_queued_again(
    queue: WikiIngestionQueue, tmp_path: Path
) -> None:
    late = tmp_path / "late.md"
    items = _processing_batch(queue, late)
    read = {items[0]["id"]: source_hash(late)}
    late.write_text("it exists now")

    settle_extracted(queue, items, read, {})

    assert queue.get_stats() == {"pending": 1, "processing": 0, "completed": 0, "failed": 0}


def test_a_source_queued_again_meanwhile_stays_queued(queue: WikiIngestionQueue, tmp_path: Path) -> None:
    again = tmp_path / "again.md"
    again.write_text("content")
    items = _processing_batch(queue, again)
    queue.add_item(again)

    settle_extracted(queue, items, {items[0]["id"]: source_hash(again)}, {})

    assert queue.get_stats() == {"pending": 1, "processing": 0, "completed": 0, "failed": 0}


@pytest.mark.parametrize(
    ("error", "kind", "retries_later"),
    [
        (RuntimeError("disk full at /Users/someone/vault/wiki/concepts/a.md"), ErrorKind.UNKNOWN, False),
        (RuntimeError("429 rate limit exceeded"), ErrorKind.RATE_LIMIT, True),
    ],
)
def test_a_failed_batch_is_recorded_with_the_extraction_classification_and_no_internals(
    queue: WikiIngestionQueue, tmp_path: Path, error: Exception, kind: ErrorKind, retries_later: bool
) -> None:
    items = _processing_batch(queue, tmp_path / "a.md", tmp_path / "b.md")

    fail_extracted(queue, [item["id"] for item in items], error)

    failed = queue.get_failed_items()
    assert {item["error_kind"] for item in failed} == {kind.value}
    assert {item["error_message"] for item in failed} == {"Compile postprocess failed"}
    assert all(bool(item["retry_after"]) is retries_later for item in failed)


_RATE_LIMITED = resolve_llm_failure(RuntimeError("429 rate limit exceeded"))
_TIMED_OUT = resolve_llm_failure(RuntimeError("Request timed out"))
_TOO_LONG = resolve_llm_failure(RuntimeError("maximum context length is 8192 tokens, however you requested 9000"))


def _failure(concept: str, sources: tuple[str, ...], resolution: FailureResolution) -> ConceptFailure:
    return ConceptFailure(name=concept, source_files=sources, resolution=resolution)


def test_a_failed_concept_blocks_every_source_it_came_from() -> None:
    failure = _failure("shared", ("a.md", "c.md"), _RATE_LIMITED)

    assert blocked_sources({"a.md": 1, "b.md": 2, "c.md": 3}, [failure]) == {1: _RATE_LIMITED, 3: _RATE_LIMITED}


def test_a_failure_naming_a_source_outside_the_batch_blocks_nothing() -> None:
    assert blocked_sources({"a.md": 1}, [_failure("x", ("elsewhere.md",), _RATE_LIMITED)]) == {}


@pytest.mark.parametrize("permanent_first", [True, False])
def test_a_permanent_failure_outranks_a_transient_one_whatever_their_order(permanent_first: bool) -> None:
    failures = [_failure("x", ("a.md",), _TOO_LONG), _failure("y", ("a.md",), _RATE_LIMITED)]
    if not permanent_first:
        failures.reverse()

    assert blocked_sources({"a.md": 1}, failures) == {1: _TOO_LONG}


@pytest.mark.parametrize("slow_first", [True, False])
def test_among_transient_failures_of_one_source_the_longest_backoff_is_kept(slow_first: bool) -> None:
    failures = [_failure("x", ("a.md",), _RATE_LIMITED), _failure("y", ("a.md",), _TIMED_OUT)]
    if not slow_first:
        failures.reverse()

    assert blocked_sources({"a.md": 1}, failures) == {1: _RATE_LIMITED}


def test_a_source_behind_a_failed_article_is_failed_with_the_classification_and_a_fixed_message(
    queue: WikiIngestionQueue, tmp_path: Path
) -> None:
    blocked, written = tmp_path / "blocked.md", tmp_path / "written.md"
    blocked.write_text("content")
    written.write_text("content")
    items = _processing_batch(queue, blocked, written)
    ids = _ids_by_name(items)
    read = {ids["blocked.md"]: source_hash(blocked), ids["written.md"]: source_hash(written)}

    settle_extracted(queue, items, read, {ids["blocked.md"]: _RATE_LIMITED})

    assert queue.get_stats() == {"pending": 0, "processing": 0, "completed": 1, "failed": 1}
    [failed] = queue.get_failed_items()
    assert failed["id"] == ids["blocked.md"]
    assert failed["error_kind"] == ErrorKind.RATE_LIMIT.value
    assert failed["retry_count"] == 1
    assert failed["retry_after"]
    # The queue panel shows this text; the provider's message (often a request id or a URL) stays in the log.
    assert failed["error_message"] == "Article generation failed"


def test_sources_blocked_by_different_failures_each_keep_their_own_classification(
    queue: WikiIngestionQueue, tmp_path: Path
) -> None:
    slow, permanent = tmp_path / "slow.md", tmp_path / "permanent.md"
    slow.write_text("content")
    permanent.write_text("content")
    items = _processing_batch(queue, slow, permanent)
    ids = _ids_by_name(items)
    read = {ids["slow.md"]: source_hash(slow), ids["permanent.md"]: source_hash(permanent)}

    settle_extracted(queue, items, read, {ids["slow.md"]: _RATE_LIMITED, ids["permanent.md"]: _TOO_LONG})

    failed = {Path(item["file_path"]).name: item for item in queue.get_failed_items()}
    assert failed["slow.md"]["error_kind"] == ErrorKind.RATE_LIMIT.value
    assert failed["slow.md"]["retry_after"]
    assert failed["permanent.md"]["error_kind"] == ErrorKind.CONTEXT_OVERFLOW.value
    assert not failed["permanent.md"]["retry_after"]


def test_a_blocked_source_that_was_edited_meanwhile_is_queued_again_instead_of_failed(
    queue: WikiIngestionQueue, tmp_path: Path
) -> None:
    edited = tmp_path / "edited.md"
    edited.write_text("version one")
    items = _processing_batch(queue, edited)
    read = {items[0]["id"]: source_hash(edited)}
    edited.write_text("version two")

    settle_extracted(queue, items, read, {items[0]["id"]: _RATE_LIMITED})

    assert queue.get_stats() == {"pending": 1, "processing": 0, "completed": 0, "failed": 0}
