"""Pure gate helpers for Managed Approval Policy enforcement.

[POS]
Single evaluation surface used by batch_processor and allow-always writers.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.managed_approval_policy import (
    ManagedApprovalPolicy,
)
from myrm_agent_harness.agent.security.types import SecurityConfig


def honor_allowlist(policy: ManagedApprovalPolicy, agent_primary_model: str) -> bool:
    if policy.should_ignore_allowlist(agent_primary_model):
        return False
    return True


def yolo_allowed(policy: ManagedApprovalPolicy) -> bool:
    return not policy.disable_yolo


def effective_auto_mode_enabled(
    config: SecurityConfig,
    policy: ManagedApprovalPolicy,
    agent_primary_model: str,
) -> bool:
    if policy.should_force_auto_review(agent_primary_model):
        return True
    return config.auto_mode_enabled


def allow_always_writes_blocked(policy: ManagedApprovalPolicy) -> bool:
    return policy.disable_allow_always
