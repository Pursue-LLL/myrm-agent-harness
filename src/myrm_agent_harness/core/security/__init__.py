"""Core security — foundational security primitives used across all layers.

This module provides security types, detection, guards, and policy
enforcement used by both ``agent/`` and ``toolkits/``. It has zero
dependency on ``agent/`` internals, enabling ``toolkits/`` to import
security capabilities without coupling to the agent framework.
"""

from myrm_agent_harness.core.security.missing_semantics import (
    MissingDependencyFailClosedError,
    MissingDependencyFailFastError,
    MissingSemanticsContract,
    MissingSemanticsError,
    MissingSemanticsPolicy,
    enforce_missing_semantics,
    get_registered_contract,
    list_registered_contracts,
)

__all__ = [
    "MissingDependencyFailClosedError",
    "MissingDependencyFailFastError",
    "MissingSemanticsContract",
    "MissingSemanticsError",
    "MissingSemanticsPolicy",
    "enforce_missing_semantics",
    "get_registered_contract",
    "list_registered_contracts",
]

