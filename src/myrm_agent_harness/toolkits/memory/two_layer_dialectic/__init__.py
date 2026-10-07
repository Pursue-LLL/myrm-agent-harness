# [POS]: myrm_agent_harness.toolkits.memory.two_layer_dialectic
# [INPUT]: .models, .reconciler, .injector
# [OUTPUT]: Two-Layer Context Injection & Multi-Pass Dialectic Reconciliation Suite symbols

"""Two-Layer Context Injection and Multi-Pass Dialectic Reconciliation Suite.

P0/P1 delivery for Item 112 in topic_01 memory roadmap.
"""

from myrm_agent_harness.toolkits.memory.two_layer_dialectic.injector import (
    TwoLayerContextInjector,
)
from myrm_agent_harness.toolkits.memory.two_layer_dialectic.models import (
    BaseContextPayload,
    DialecticConflictCandidate,
    DialecticPassKind,
    DialecticReconciliationConfig,
    DialecticReconciliationResult,
    TwoLayerContextInjectionResult,
)
from myrm_agent_harness.toolkits.memory.two_layer_dialectic.reconciler import (
    MultiPassDialecticReconciler,
)

__all__ = [
    "BaseContextPayload",
    "DialecticConflictCandidate",
    "DialecticPassKind",
    "DialecticReconciliationConfig",
    "DialecticReconciliationResult",
    "MultiPassDialecticReconciler",
    "TwoLayerContextInjectionResult",
    "TwoLayerContextInjector",
]
