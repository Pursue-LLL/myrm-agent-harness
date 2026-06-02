"""Security and policy enforcement metrics.

[INPUT]
- (none — pure metrics definition)

[OUTPUT]
- policy_denial_total — Counter for blocked actions

[POS]
Harness-layer generic security monitoring metrics.
"""

from __future__ import annotations

from myrm_agent_harness.observability.metrics import create_counter

policy_denial_total = create_counter(
    "policy_denial_total",
    "Total number of actions blocked or redacted by security policy gate",
    ("policy", "action"),
)

__all__ = [
    "policy_denial_total",
]
