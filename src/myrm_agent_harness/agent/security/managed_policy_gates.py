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
    return not policy.should_ignore_allowlist(agent_primary_model)


def yolo_allowed(policy: ManagedApprovalPolicy) -> bool:
    return not policy.disable_yolo


def map_suppresses_yolo(policy: ManagedApprovalPolicy, agent_primary_model: str) -> bool:
    """Org MAP requires review path for this model (no YOLO fast path)."""
    return policy.should_force_auto_review(
        agent_primary_model
    ) or policy.should_ignore_allowlist(agent_primary_model)


def yolo_allowed_for_model(
    policy: ManagedApprovalPolicy,
    agent_primary_model: str,
) -> bool:
    if not yolo_allowed(policy):
        return False
    return not map_suppresses_yolo(policy, agent_primary_model)


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
