"""Workspace living governance and documentation synchronization toolkit.

[INPUT]
- toolkits.memory.workspace_living.merger::CausalIssueMerger (POS: Concurrency-safe, idempotent file merger for living environmental known issues)
- toolkits.memory.workspace_living.models::ADRMetadata, CausalDeduplicationReport, KnownIssueEntry, compute_error_signature (POS: Domain contract layer for workspace living documentation synchronization)

[OUTPUT]
- ADRMetadata: Architectural decision record domain entity
- CausalDeduplicationReport: Report detailing merge outcome
- CausalIssueMerger: Atomic deduplication merger
- KnownIssueEntry: Living environment issue entry model
- compute_error_signature: Causal signature fingerprint generator

[POS]
Toolkit module boundary for living workspace documentation synchronization and causal deduplication.
"""

from __future__ import annotations

from .merger import CausalIssueMerger
from .models import (
    ADRMetadata,
    CausalDeduplicationReport,
    KnownIssueEntry,
    compute_error_signature,
)

__all__ = [
    "ADRMetadata",
    "CausalDeduplicationReport",
    "CausalIssueMerger",
    "KnownIssueEntry",
    "compute_error_signature",
]
