"""
[INPUT]
models.py, base_context_engine.py, dialectic_engine.py, orchestrator.py

[OUTPUT]
Unified public exports for TwoLayerContextInjectionAndMultiPassDialecticReconciliationSuite.

[POS]
Package facade for Item 112 in Harness framework.
Strict typing applied: No `Any` types allowed. Single file < 90 lines.
"""

from myrm_agent_harness.toolkits.memory.two_layer_dialectic.base_context_engine import (
    BaseContextEngine,
)
from myrm_agent_harness.toolkits.memory.two_layer_dialectic.dialectic_engine import (
    DialecticReconciliationEngine,
)
from myrm_agent_harness.toolkits.memory.two_layer_dialectic.injector import (
    TwoLayerContextInjector,
)
from myrm_agent_harness.toolkits.memory.two_layer_dialectic.models import (
    BaseContextBundle,
    ConflictItem,
    DialecticCadenceConfig,
    DialecticPassRecord,
    DialecticReasoningLevel,
    DialecticReconciliationResult,
    TwoLayerContextInjectionResult,
)
from myrm_agent_harness.toolkits.memory.two_layer_dialectic.orchestrator import (
    TwoLayerDialecticOrchestrator,
    TwoLayerInvocationPayload,
)

# Standard alias bindings for canonical alignment
BaseContextPayload = BaseContextBundle
DialecticConflictCandidate = ConflictItem
DialecticPassKind = DialecticReasoningLevel
DialecticReconciliationConfig = DialecticCadenceConfig
MultiPassDialecticReconciler = DialecticReconciliationEngine

__all__ = [
    "BaseContextBundle",
    "BaseContextEngine",
    "BaseContextPayload",
    "ConflictItem",
    "DialecticCadenceConfig",
    "DialecticConflictCandidate",
    "DialecticPassKind",
    "DialecticPassRecord",
    "DialecticReasoningLevel",
    "DialecticReconciliationConfig",
    "DialecticReconciliationEngine",
    "DialecticReconciliationResult",
    "MultiPassDialecticReconciler",
    "TwoLayerContextInjectionResult",
    "TwoLayerContextInjector",
    "TwoLayerDialecticOrchestrator",
    "TwoLayerInvocationPayload",
]

# Lab / legacy orchestrator payload alias (prefer TwoLayerContextInjectionResult from models)
LabTwoLayerInvocationPayload = TwoLayerInvocationPayload
