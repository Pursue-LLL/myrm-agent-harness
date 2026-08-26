"""Core security — foundational security primitives used across all layers.

[INPUT]
- myrm_agent_harness.core.security.missing_semantics (POS: Missing semantics contract and evaluation)

[OUTPUT]
- MissingSemanticsPolicy, MissingSemanticsDecision, enforce_missing_semantics, evaluate_missing_capability: security API

[POS]
Core security exports. Foundational security primitives used across all layers.
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
