"""Companion relationship safety and decorum guard suite.

[INPUT]
- User dialogue, proposed assistant response, local timing, commercial intent.

[OUTPUT]
- Decorum verdicts, compliance violations, and sanitized response redirections.

[POS]
- Harness core security module defining decorum and compliance boundaries for relationship-oriented AI companions.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.companion_relationship_guard.guard import (
    CompanionRelationshipSafetyGuard,
)
from myrm_agent_harness.core.security.companion_relationship_guard.types import (
    CompanionGuardContext,
    CompanionSafetyVerdict,
    CompanionViolationCategory,
)

__all__ = [
    "CompanionGuardContext",
    "CompanionRelationshipSafetyGuard",
    "CompanionSafetyVerdict",
    "CompanionViolationCategory",
]
