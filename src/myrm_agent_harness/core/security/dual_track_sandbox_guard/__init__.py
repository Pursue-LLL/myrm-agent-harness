"""Dual-Track Soft Memory vs Hard Redline Sandbox Guard Suite.

[INPUT]
- Hard redline compilation, physical sandbox firewall interception, soft memory decoupling.

[OUTPUT]
- Public exports of domain types, policy compiler, and sandbox guard interceptor.

[POS]
- Harness core security package guaranteeing deterministic enforcement over prompt suggestions.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.dual_track_sandbox_guard.guard_interceptor import (
    DualTrackSandboxGuard,
)
from myrm_agent_harness.core.security.dual_track_sandbox_guard.policy_compiler import (
    RedlinePolicyCompiler,
)
from myrm_agent_harness.core.security.dual_track_sandbox_guard.types import (
    CognitionTrack,
    CompiledSandboxFirewallPolicy,
    ExecutionInterceptionVerdict,
    HardRedlineRule,
    InterceptionVerdict,
    RedlineCategory,
    SoftMemoryRecord,
)

__all__ = [
    "CognitionTrack",
    "CompiledSandboxFirewallPolicy",
    "DualTrackSandboxGuard",
    "ExecutionInterceptionVerdict",
    "HardRedlineRule",
    "InterceptionVerdict",
    "RedlineCategory",
    "RedlinePolicyCompiler",
    "SoftMemoryRecord",
]
