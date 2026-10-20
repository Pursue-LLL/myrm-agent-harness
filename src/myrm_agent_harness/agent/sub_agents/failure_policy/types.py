"""Strongly-typed data contracts for Per-Role Subagent Failure Restart & Redeploy Policy (Item 35).

[INPUT]
- Subagent failure events, mid-task crashes, spec mismatches, and execution timeouts.

[OUTPUT]
- Strongly-typed failure actions, declarative policies, and remediation evaluation decisions.

[POS]
- Harness sub_agents layer for autonomous per-role fault isolation, restarts, and escalations.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class FailureAction(enum.StrEnum):
    """Autonomous remediation actions executable by the orchestrator."""

    RESTART_FRESH = "restart_fresh"
    REDEPLOY_SPECS = "redeploy_specs"
    ESCALATE_PARENT = "escalate_parent"
    SKIP = "skip"


class FailureTriggerReason(enum.StrEnum):
    """Categorized root causes triggering failure policy evaluation."""

    CRASH_ERROR = "crash_error"
    STUCK_TIMEOUT = "stuck_timeout"
    OUTPUT_SPEC_MISMATCH = "output_spec_mismatch"
    TOOL_QUOTA_EXHAUSTED = "tool_quota_exhausted"


@dataclass(frozen=True)
class RoleFailurePolicy:
    """Declarative remediation policy bound to a specific subagent role."""

    role_key: str
    primary_action: FailureAction = FailureAction.RESTART_FRESH
    allow_failure: bool = False
    max_retries: int = 2
    fallback_action: FailureAction = FailureAction.ESCALATE_PARENT
    fresh_instructions_template: str = ""
    redeploy_model_tier_downgrade: bool = False


@dataclass(frozen=True)
class FailureEvent:
    """Mid-task execution failure event emitted during subagent lifecycle."""

    event_id: str
    task_id: str
    role_key: str
    trigger_reason: FailureTriggerReason
    error_message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class PolicyEvaluationDecision:
    """Orchestrator remediation decision produced by evaluating a FailureEvent against role policy."""

    event_id: str
    task_id: str
    role_key: str
    action: FailureAction
    attempt_number: int
    max_retries: int
    rationale: str
    redeploy_payload: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
