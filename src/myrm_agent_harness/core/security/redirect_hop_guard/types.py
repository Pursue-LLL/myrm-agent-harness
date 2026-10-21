"""Type definitions for Redirect Private Address Hop Revalidation Suite.

[INPUT]
- stdlib dataclasses, enum

[OUTPUT]
- HopDisposition: enum of routing enforcement actions
- HopEvaluationResult: per-request hop evaluation outcome

[POS]
Hop disposition and evaluation-result schema returned by RedirectHopEvaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HopDisposition(StrEnum):
    """Routing enforcement actions taken on a network hop."""

    ALLOW = "ALLOW"
    ABORT_SUBRESOURCE = "ABORT_SUBRESOURCE"
    ABORT_AND_RESET_DOCUMENT = "ABORT_AND_RESET_DOCUMENT"


@dataclass(frozen=True, slots=True)
class HopEvaluationResult:
    """Outcome of inspecting an individual request or redirect hop."""

    disposition: HopDisposition
    is_private: bool
    matched_rule: str
    target_url: str
    resource_type: str
    reason: str
