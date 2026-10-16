"""Settle the queue rows of a compile batch once its results are written.

[INPUT]
- ..core.claims_contract::sha256_raw_file (POS: the content hash incremental compile compares against)
- .articles::ConceptFailure (POS: a concept whose article could not be written, with its sources)
- .queue::QueueItem, WikiIngestionQueue (POS: persistent ingestion queue)
- .resilience::FailureResolution, is_transient_error_kind, resolve_llm_failure (POS: failure classification shared with extraction)
- utils.logger_utils::get_agent_logger (POS: agent logger)

[OUTPUT]
- source_hash: SHA256 of a raw file, ``None`` when it cannot be read
- blocked_sources: the failure that keeps each source of a batch from being complete, from the articles that failed
- settle_extracted: complete the sources a batch finished, fail the ones with a missing article, queue again the ones edited while it ran
- fail_extracted: fail the sources whose batch raised after their concepts were extracted

[POS]
Batch settlement. A batch's sources stay ``processing`` until everything the compile writes for them is saved;
this module decides what each of them becomes then. Metadata records the hashes of the files as they are when
it is saved, and the compile intake skips files that are ``processing``, so a source edited while its batch ran
would otherwise be marked completed with its new content never compiled.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.claims_contract import sha256_raw_file
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .articles import ConceptFailure
from .queue import QueueItem, WikiIngestionQueue
from .resilience import FailureResolution, is_transient_error_kind, resolve_llm_failure

logger = get_agent_logger(__name__)

# The queue panel shows these texts to the user; the raw exception (often a path, a request id or a sqlite error)
# stays in the log, and the error kind carries the classification.
_POSTPROCESS_FAILED = "Compile postprocess failed"
_ARTICLE_FAILED = "Article generation failed"


def source_hash(path: Path) -> str | None:
    """SHA256 of a raw file, or ``None`` when it is missing or unreadable."""
    try:
        return sha256_raw_file(path)
    except OSError:
        return None


def _severity(resolution: FailureResolution) -> tuple[bool, int]:
    """Orders failures by what a source needs: a permanent one will not clear by itself, so it outranks any transient
    one; among transient failures the longer backoff is the one to wait for."""
    return (not is_transient_error_kind(resolution.error_kind), resolution.retry_after_seconds)


def blocked_sources(
    item_ids_by_source: Mapping[str, int], failures: Sequence[ConceptFailure]
) -> dict[int, FailureResolution]:
    """The failure that keeps each source from being complete: a concept's article failing blocks every source it
    was extracted from, and a source blocked by several concepts keeps the most severe failure.

    Args:
        item_ids_by_source: The queue row of each source of the batch, by the source name concepts carry.
        failures: The concepts whose article could not be written.
    """
    blocked: dict[int, FailureResolution] = {}
    for failure in failures:
        for source in failure.source_files:
            item_id = item_ids_by_source.get(source)
            if item_id is None:
                continue
            current = blocked.get(item_id)
            if current is None or _severity(failure.resolution) > _severity(current):
                blocked[item_id] = failure.resolution
    return blocked


def settle_extracted(
    queue: WikiIngestionQueue,
    items: Sequence[QueueItem],
    read_hashes: Mapping[int, str | None],
    blocked: Mapping[int, FailureResolution],
) -> None:
    """Settle the sources whose concepts were extracted, now that the batch has saved what it writes.

    A source whose file changed since extraction read it is queued again, whatever else happened: its results
    are about text that no longer exists. Otherwise it is failed when ``blocked`` names a failure that kept an
    article from being written, so the queue shows it and a retry can fix it, and completed when it is not.
    A file that can no longer be read counts as unchanged: the compile already has what it needs from it.
    """
    paths = {item["id"]: Path(item["file_path"]) for item in items}
    done: list[int] = []
    edited: list[int] = []
    failed: dict[FailureResolution, list[int]] = {}
    for item_id, before in read_hashes.items():
        after = source_hash(paths[item_id])
        if after is not None and after != before:
            edited.append(item_id)
        elif item_id in blocked:
            failed.setdefault(blocked[item_id], []).append(item_id)
        else:
            done.append(item_id)
    queue.complete_processing(done)
    for resolution, item_ids in failed.items():
        logger.info(f"{len(item_ids)} source(s) have an article that failed ({resolution.error_kind}); marked failed")
        queue.fail_processing(
            item_ids,
            _ARTICLE_FAILED,
            error_kind=resolution.error_kind,
            retry_after_seconds=resolution.retry_after_seconds,
        )
    if edited:
        logger.info(f"{len(edited)} source(s) changed while their batch compiled; queued again")
        queue.requeue_processing(edited)


def fail_extracted(queue: WikiIngestionQueue, item_ids: Sequence[int], error: Exception) -> None:
    """Fail the sources whose batch raised after extraction, classified like an extraction failure."""
    resolution = resolve_llm_failure(error)
    queue.fail_processing(
        item_ids,
        _POSTPROCESS_FAILED,
        error_kind=resolution.error_kind,
        retry_after_seconds=resolution.retry_after_seconds,
    )
