"""Merkle chain integrity for cron run records.

Pure functions — no I/O, no side effects, fully testable.

Each job maintains an independent hash chain: every new CronRunRecord
includes the hash of the previous record.  Tampering with any record
(insert, delete, modify) breaks the chain and is detectable via
``verify_chain()``.

Hash algorithm: SHA-256 over a canonical pipe-delimited string that
covers all security-relevant fields plus the content hashes of
variable-length fields (output, metadata).

[INPUT]
- toolkits.cron.types::CronRunRecord (POS: Cron job domain types.)

[OUTPUT]
- ChainBreak: Describes a single integrity violation in the Merkle chain.
- compute_integrity_hash: function — compute_integrity_hash
- verify_chain: Verify Merkle chain integrity for a sequence of runs.

[POS]
Merkle chain integrity for cron run records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.cron.types import CronRunRecord

GENESIS_HASH = "0" * 64

ChainBreakKind = Literal["prev_hash_mismatch", "integrity_hash_mismatch"]


@dataclass(frozen=True, slots=True)
class ChainBreak:
    """Describes a single integrity violation in the Merkle chain."""

    run_id: str
    kind: ChainBreakKind
    expected: str
    actual: str


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def compute_integrity_hash(run: CronRunRecord, prev_hash: str) -> str:
    """Compute the Merkle hash for a single run record.

    The canonical string is a pipe-delimited concatenation of:
    prev_hash | job_id | run_id | started_at (ISO) | status |
    SHA256(output) | SHA256(metadata JSON).

    Variable-length fields (output, metadata) are hashed individually
    to keep the canonical string compact and constant-size.
    """
    output_hash = _sha256(run.output or "")
    metadata_hash = _sha256(json.dumps(run.metadata or {}, sort_keys=True, ensure_ascii=False))
    canonical = "|".join(
        [
            prev_hash,
            run.job_id,
            run.id,
            run.started_at.isoformat(),
            run.status.value,
            output_hash,
            metadata_hash,
        ]
    )
    return _sha256(canonical)


def verify_chain(runs: list[CronRunRecord]) -> list[ChainBreak]:
    """Verify Merkle chain integrity for a sequence of runs.

    ``runs`` must be sorted oldest-first (ascending ``started_at``).
    Returns an empty list when the chain is intact.
    """
    breaks: list[ChainBreak] = []
    expected_prev = GENESIS_HASH

    for run in runs:
        if not run.integrity_hash:
            break

        if run.prev_hash != expected_prev:
            breaks.append(
                ChainBreak(
                    run_id=run.id,
                    kind="prev_hash_mismatch",
                    expected=expected_prev,
                    actual=run.prev_hash,
                )
            )

        recomputed = compute_integrity_hash(run, run.prev_hash)
        if run.integrity_hash != recomputed:
            breaks.append(
                ChainBreak(
                    run_id=run.id,
                    kind="integrity_hash_mismatch",
                    expected=recomputed,
                    actual=run.integrity_hash,
                )
            )

        expected_prev = run.integrity_hash

    return breaks
