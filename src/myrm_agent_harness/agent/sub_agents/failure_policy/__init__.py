"""Per-Role Subagent Failure Restart & Redeploy Policy (Item 35).

Exports failure action types, trigger reasons, declarative policies, and policy engine.

[INPUT]
- __future__
- policy_engine
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Per-Role Subagent Failure Restart & Redeploy Policy (Item 35).
"""

from __future__ import annotations

from .policy_engine import RoleFailurePolicyEngine
from .types import (
    FailureAction,
    FailureEvent,
    FailureTriggerReason,
    PolicyEvaluationDecision,
    RoleFailurePolicy,
)

__all__ = [
    "FailureAction",
    "FailureEvent",
    "FailureTriggerReason",
    "PolicyEvaluationDecision",
    "RoleFailurePolicy",
    "RoleFailurePolicyEngine",
]
