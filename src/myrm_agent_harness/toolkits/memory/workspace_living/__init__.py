"""Workspace living governance and documentation synchronization toolkit.

Exports core models and deduplication merger for architectural decisions (ADRs)
and living environment pitfalls (KNOWN_ISSUES.md).
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
