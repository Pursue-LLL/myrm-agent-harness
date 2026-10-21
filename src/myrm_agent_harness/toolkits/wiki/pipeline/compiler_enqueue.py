"""Queue the raw sources a wiki compile has to read.

[INPUT]
- ..core.claims_contract::get_last_compile_raw_hashes, raw_relative_storage_key (POS: stored raw hashes and portable raw keys)
- ..core.structure::WikiStructure (POS: raw file listing and metadata path)
- .queue::WikiIngestionQueue (POS: persistent ingestion queue)
- utils.logger_utils::get_agent_logger (POS: agent logger)

[OUTPUT]
- enqueue_changed_sources: queue the raw files a compile must read, return how many
- filter_changed_files: the raw files whose SHA256 differs from the last compile

[POS]
Compile intake. Decides which raw files go onto the queue (changed ones when incremental, all when full) and
leaves the compiling to the background worker. Kept separate from ``compiler.py`` so the compiler module stays
within the file-line governance baseline while the intake rules remain independently testable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.claims_contract import get_last_compile_raw_hashes, raw_relative_storage_key
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .queue import WikiIngestionQueue

logger = get_agent_logger(__name__)


async def enqueue_changed_sources(structure: WikiStructure, queue: WikiIngestionQueue, *, incremental: bool) -> int:
    """Queue the raw files a compile has to read: the new or changed ones, or all of them when not incremental.

    Nothing is compiled here; the background worker drains the queue. A file the worker is compiling right now is
    left alone: queueing it again would put it back to pending while the worker still holds it, and the queue
    would report no work in progress.

    Returns:
        How many files were queued.
    """
    from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.eligibility import CorpusEligibilityFilter

    raw_files = CorpusEligibilityFilter(structure).filter_raw_paths(structure.list_raw_files())
    files = await filter_changed_files(structure, raw_files) if incremental else raw_files
    # Read after the last await, so the worker cannot claim a file between this check and the write below.
    in_flight = set(queue.list_processing_file_paths())
    files = [path for path in files if str(path) not in in_flight]
    logger.info(f"{'Incremental' if incremental else 'Full'} compile: adding {len(files)} files to queue")
    if files:
        queue.add_batch(files)
    return len(files)


async def filter_changed_files(structure: WikiStructure, raw_files: list[Path]) -> list[Path]:
    """Filter for new or changed files using SHA256 content hashing."""
    metadata_path = structure.get_wiki_metadata_path()
    if not metadata_path.exists():
        return raw_files

    try:
        with open(metadata_path, encoding="utf-8") as meta_f:
            metadata = json.load(meta_f)
        known_hashes = get_last_compile_raw_hashes(metadata)
    except Exception as e:
        logger.warning(f"Failed to read metadata: {e}")
        return raw_files

    # Hashing every raw file takes seconds on a large vault; on a worker thread it does not stall SSE or requests.
    return await asyncio.to_thread(_changed_by_hash, structure, raw_files, known_hashes)


def _changed_by_hash(structure: WikiStructure, raw_files: list[Path], known_hashes: dict[str, str]) -> list[Path]:
    changed: list[Path] = []
    for f in raw_files:
        try:
            content_hash = hashlib.sha256(f.read_bytes()).hexdigest()
            storage_key = raw_relative_storage_key(structure, f)
            if known_hashes.get(storage_key) != content_hash:
                changed.append(f)
        except OSError:
            changed.append(f)
    return changed
