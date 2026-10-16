"""Settle the queue rows of a compile batch once its results are written.

[INPUT]
- ..core.claims_contract::sha256_raw_file (POS: the content hash incremental compile compares against)
- .queue::QueueItem, WikiIngestionQueue (POS: persistent ingestion queue)
- .resilience::resolve_llm_failure (POS: failure classification shared with extraction)
- utils.logger_utils::get_agent_logger (POS: agent logger)

[OUTPUT]
- source_hash: SHA256 of a raw file, ``None`` when it cannot be read
- settle_extracted: complete the sources a batch finished, queue again the ones edited while it ran
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

from .queue import QueueItem, WikiIngestionQueue
from .resilience import resolve_llm_failure

logger = get_agent_logger(__name__)

# The queue panel shows this text to the user; the raw exception (often a path or a sqlite error) stays in the
# log, and the error kind carries the classification.
_POSTPROCESS_FAILED = "Compile postprocess failed"


def source_hash(path: Path) -> str | None:
    """SHA256 of a raw file, or ``None`` when it is missing or unreadable."""
    try:
        return sha256_raw_file(path)
    except OSError:
        return None


def settle_extracted(
    queue: WikiIngestionQueue, items: Sequence[QueueItem], read_hashes: Mapping[int, str | None]
) -> None:
    """Complete the sources whose files are as extraction read them; queue the edited ones again.

    A file that can no longer be read is settled as it always was: the compile has what it needs from it.
    """
    paths = {item["id"]: Path(item["file_path"]) for item in items}
    done: list[int] = []
    edited: list[int] = []
    for item_id, before in read_hashes.items():
        after = source_hash(paths[item_id])
        (edited if after is not None and after != before else done).append(item_id)
    queue.complete_processing(done)
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
