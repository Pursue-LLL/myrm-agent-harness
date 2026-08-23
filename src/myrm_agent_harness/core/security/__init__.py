"""Core security — foundational security primitives used across all layers.

This module provides security types, detection, guards, and policy
enforcement used by both ``agent/`` and ``toolkits/``. It has zero
dependency on ``agent/`` internals, enabling ``toolkits/`` to import
security capabilities without coupling to the agent framework.
"""

from myrm_agent_harness.core.security.missing_semantics import (
    MissingSemanticsBlockedError,
    MissingSemanticsContract,
    MissingSemanticsDecision,
    MissingSemanticsPolicy,
    SemanticsCategory,
    evaluate_missing_capability,
    get_missing_semantics_matrix,
)

__all__ = [
    "MissingSemanticsBlockedError",
    "MissingSemanticsContract",
    "MissingSemanticsDecision",
    "MissingSemanticsPolicy",
    "SemanticsCategory",
    "evaluate_missing_capability",
    "get_missing_semantics_matrix",
]
