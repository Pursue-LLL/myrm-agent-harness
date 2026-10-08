"""Proactive Agent Micro-Kernel Contract and Instinctive Proactivity Loop package.

[INPUT]
- proactive_kernel_types::* (POS: Type definitions)
- heartbeat_manifest_parser::HeartbeatManifestParser (POS: Manifest parser)
- opportunity_sensing_engine::OpportunitySensingEngine (POS: Opportunity sensing engine)
- zero_nag_discretion_gate::ZeroNagDiscretionGate (POS: Discretion gate)
- proactive_agent_kernel_suite::ProactiveAgentKernelSuite, ProactiveAgentKernelContractAndInstinctiveProactivityLoopSuite (POS: Facade suites)

[OUTPUT]
- Public exports for proactive agent micro-kernel, heartbeat loops, and zero-nag gates.

[POS]
Exports for OpenClaw-inspired Markdown heartbeat manifests, background autonomous
opportunity sensing, and low-friction etiquette gates.
"""

from __future__ import annotations

from .heartbeat_manifest_parser import HeartbeatManifestParser
from .opportunity_sensing_engine import OpportunitySensingEngine
from .proactive_agent_kernel_suite import (
    ProactiveAgentKernelContractAndInstinctiveProactivityLoopSuite,
    ProactiveAgentKernelSuite,
)
from .proactive_kernel_types import (
    HeartbeatChecklistItem,
    HeartbeatManifest,
    OpportunityCategory,
    ProactiveHeartbeatResult,
    ProactiveOpportunity,
    ProactivityDiscretionTier,
    ProactivityLevel,
)
from .zero_nag_discretion_gate import ZeroNagDiscretionGate

__all__ = [
    "HeartbeatChecklistItem",
    "HeartbeatManifest",
    "HeartbeatManifestParser",
    "OpportunityCategory",
    "OpportunitySensingEngine",
    "ProactiveAgentKernelContractAndInstinctiveProactivityLoopSuite",
    "ProactiveAgentKernelSuite",
    "ProactiveHeartbeatResult",
    "ProactiveOpportunity",
    "ProactivityDiscretionTier",
    "ProactivityLevel",
    "ZeroNagDiscretionGate",
]
