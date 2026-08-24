"""Core security — foundational security primitives used across all layers.

This module provides security types, detection, guards, and policy
enforcement used by both ``agent/`` and ``toolkits/``. It has zero
dependency on ``agent/`` internals, enabling ``toolkits/`` to import
security capabilities without coupling to the agent framework.
"""

from myrm_agent_harness.core.security.missing_semantics import (
    MissingDependencyFailClosedError,
    MissingDependencyFailFastError,
    MissingSemanticsBlockedError,
    MissingSemanticsContract,
    MissingSemanticsDecision,
    MissingSemanticsError,
    MissingSemanticsPolicy,
    SemanticsCategory,
    enforce_missing_semantics,
    evaluate_missing_capability,
    get_missing_semantics_matrix,
    get_registered_contract,
    list_registered_contracts,
    register_missing_semantics_contract,
)

__all__ = [
    "MissingDependencyFailClosedError",
    "MissingDependencyFailFastError",
    "MissingSemanticsBlockedError",
    "MissingSemanticsContract",
    "MissingSemanticsDecision",
    "MissingSemanticsError",
    "MissingSemanticsPolicy",
    "SemanticsCategory",
    "enforce_missing_semantics",
    "evaluate_missing_capability",
    "get_missing_semantics_matrix",
    "get_registered_contract",
    "list_registered_contracts",
    "register_missing_semantics_contract",
]
