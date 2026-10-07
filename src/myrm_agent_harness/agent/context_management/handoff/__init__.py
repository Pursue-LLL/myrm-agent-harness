"""Public interface for agent handoff management and session finalization.

Provides typed models, state machine, storage engine, and finalization routines
for cross-agent, cross-session execution relay.
Strict typing applied: No `Any` types allowed.

[INPUT]
- agent.context_management.handoff.engine::AgentHandoffEngine (POS: Unified facade for agent handoff
  management, exactly-once claim, and session finalization.)
- agent.context_management.handoff.finalizer::SessionFinalizationError, SessionFinalizer (POS: Session
  finalizer responsible for extracting and persisting durable handoffs upon session close.)
- agent.context_management.handoff.handoff_store::AgentHandoffStore (POS: Persistent storage backend for
  agent handoff packets.)
- agent.context_management.handoff.state_machine::ExactlyOnceHandoffMachine, HandoffAlreadyClaimedError,
  HandoffAlreadyCompletedError, HandoffError, HandoffInvalidTransitionError, HandoffNotFoundError,
  HandoffTargetMismatchError (POS: State machine governing exactly-once claim and state transitions for
  agent handoffs.)
- agent.context_management.handoff.types::AgentHandoffSpec, FailedApproachRecord, FinalizeSessionRequest,
  FinalizeSessionResult, HandoffClaimReceipt, HandoffStatus, ImplicitConstraintRecord (POS: Type definitions
  for cross-agent/cross-session typed handoff protocol.)

[OUTPUT]
- Package facade re-exporting 18 public names: AgentHandoffEngine, AgentHandoffSpec, AgentHandoffStore,
  ExactlyOnceHandoffMachine, FailedApproachRecord, FinalizeSessionRequest, FinalizeSessionResult,
  HandoffAlreadyClaimedError, HandoffAlreadyCompletedError, HandoffClaimReceipt, HandoffError,
  HandoffInvalidTransitionError, HandoffNotFoundError, HandoffStatus (+4 more)

[POS]
Public interface for agent handoff management and session finalization.
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
