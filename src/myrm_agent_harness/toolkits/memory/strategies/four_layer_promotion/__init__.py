"""Four-Layer Memory Tri-Channel Promotion and Anti-Poisoning Audit Package.

[INPUT]
- Candidate events, sessions, and tool outcomes
- types: MemoryLayer, PromotionChannel, ExposureSource, CandidateStatement, CapabilityMethod

[OUTPUT]
- TriChannelPromotionGate: code-level deterministic promotion gate
- TwoStepMapReduceConsolidationEngine: Map-Reduce consolidation and structured compliance verification
- AntiPoisoningAuditTracker: batch lineage and atomic rollback tracker

[POS]
Harness memory strategy implementing Hermes-grade four-layer progressive memory,
two-step Map-Reduce consolidation, and tri-channel anti-poisoning governance.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.strategies.four_layer_promotion.anti_poisoning_audit import (
    AntiPoisoningAuditTracker,
    ConsolidationBatchRecord,
)
from myrm_agent_harness.toolkits.memory.strategies.four_layer_promotion.map_reduce_engine import (
    TwoStepMapReduceConsolidationEngine,
)
from myrm_agent_harness.toolkits.memory.strategies.four_layer_promotion.promotion_gate import (
    TriChannelPromotionGate,
)
from myrm_agent_harness.toolkits.memory.strategies.four_layer_promotion.types import (
    CandidateStatement,
    CapabilityMethod,
    ExposureSource,
    MemoryLayer,
    PromotionChannel,
    PromotionDecision,
    RulesComplianceItem,
)

__all__ = [
    "AntiPoisoningAuditTracker",
    "CandidateStatement",
    "CapabilityMethod",
    "ConsolidationBatchRecord",
    "ExposureSource",
    "MemoryLayer",
    "PromotionChannel",
    "PromotionDecision",
    "RulesComplianceItem",
    "TriChannelPromotionGate",
    "TwoStepMapReduceConsolidationEngine",
]
