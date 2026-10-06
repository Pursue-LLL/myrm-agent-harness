# [POS]: myrm_agent_harness/agent/context_management/handoff/__init__.py
# [INPUT]: None
# [OUTPUT]: AgentHandoffEngine, AgentHandoffStore, ExactlyOnceHandoffMachine, SessionFinalizer, Types
"""Public interface for agent handoff management and session finalization.

Provides typed models, state machine, storage engine, and finalization routines
for cross-agent, cross-session execution relay.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.handoff.engine import AgentHandoffEngine
from myrm_agent_harness.agent.context_management.handoff.finalizer import (
    SessionFinalizationError,
    SessionFinalizer,
)
from myrm_agent_harness.agent.context_management.handoff.handoff_store import AgentHandoffStore
from myrm_agent_harness.agent.context_management.handoff.state_machine import (
    ExactlyOnceHandoffMachine,
    HandoffAlreadyClaimedError,
    HandoffAlreadyCompletedError,
    HandoffError,
    HandoffInvalidTransitionError,
    HandoffNotFoundError,
    HandoffTargetMismatchError,
)
from myrm_agent_harness.agent.context_management.handoff.types import (
    AgentHandoffSpec,
    FailedApproachRecord,
    FinalizeSessionRequest,
    FinalizeSessionResult,
    HandoffClaimReceipt,
    HandoffStatus,
    ImplicitConstraintRecord,
)

__all__ = [
    "AgentHandoffEngine",
    "AgentHandoffSpec",
    "AgentHandoffStore",
    "ExactlyOnceHandoffMachine",
    "FailedApproachRecord",
    "FinalizeSessionRequest",
    "FinalizeSessionResult",
    "HandoffAlreadyClaimedError",
    "HandoffAlreadyCompletedError",
    "HandoffClaimReceipt",
    "HandoffError",
    "HandoffInvalidTransitionError",
    "HandoffNotFoundError",
    "HandoffStatus",
    "HandoffTargetMismatchError",
    "ImplicitConstraintRecord",
    "SessionFinalizationError",
    "SessionFinalizer",
]
