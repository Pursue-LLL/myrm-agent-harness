"""Human-in-the-Loop (HITL) denial events and workflow coordination.

Provides primitives for emitting explicit tool_result events on manual denial,
custom denial reasoning, and handling all-tools-denied aggregate events
supporting both halting and resuming with feedback.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.hitl_denial_events.dispatcher import (
    DEFAULT_APPROVAL_MESSAGE,
    DEFAULT_DENIAL_REASON,
    HitlDenialEventDispatcher,
)
from myrm_agent_harness.core.security.hitl_denial_events.policy_evaluator import (
    AllToolsDeniedPolicyEvaluator,
)
from myrm_agent_harness.core.security.hitl_denial_events.types import (
    AllToolsDeniedEvent,
    AllToolsDeniedPolicy,
    ConfirmResult,
    HitlProcessOutcome,
    ToolResultEvent,
    ToolResultState,
    ToolUseBlock,
)

__all__ = [
    "DEFAULT_APPROVAL_MESSAGE",
    "DEFAULT_DENIAL_REASON",
    "AllToolsDeniedEvent",
    "AllToolsDeniedPolicy",
    "AllToolsDeniedPolicyEvaluator",
    "ConfirmResult",
    "HitlDenialEventDispatcher",
    "HitlProcessOutcome",
    "ToolResultEvent",
    "ToolResultState",
    "ToolUseBlock",
]
