"""Runtime Invariant Subsystem.

[INPUT]
- types::(InvariantViolation, InvariantSeverity, InvariantCheckerProtocol)
- registry::(RuntimeInvariantRegistry, InvariantError, InvariantMode, default_invariant_registry)
- core_pack::(install_core_invariants, check_session_event_pairing, check_agent_state_transition, check_todo_structure_integrity)

[OUTPUT]
- Public exports for runtime invariant assertions and registry services

[POS]
Package entry point exposing invariant types, registry, and core companion checks.
"""

from __future__ import annotations

from myrm_agent_harness.observability.invariants.core_pack import (
    check_agent_state_transition,
    check_session_event_pairing,
    check_todo_structure_integrity,
    install_core_invariants,
)
from myrm_agent_harness.observability.invariants.registry import (
    InvariantError,
    InvariantMode,
    RuntimeInvariantRegistry,
    default_invariant_registry,
)
from myrm_agent_harness.observability.invariants.types import (
    InvariantCheckerProtocol,
    InvariantSeverity,
    InvariantViolation,
)

__all__ = [
    "InvariantCheckerProtocol",
    "InvariantError",
    "InvariantMode",
    "InvariantSeverity",
    "InvariantViolation",
    "RuntimeInvariantRegistry",
    "check_agent_state_transition",
    "check_session_event_pairing",
    "check_todo_structure_integrity",
    "default_invariant_registry",
    "install_core_invariants",
]
