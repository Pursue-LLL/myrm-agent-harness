"""Zero-hallucination memory retrieval protocol and explicit state error package.

[POS]
src/myrm_agent_harness/toolkits/memory/zero_hallucination/__init__.py
Exposes defensive tri-state assertions, prompt guards, and state assertion evaluators.

[INPUT]
- .models: (MemoryFactItem, MemoryRetrievalState, RetrievalErrorSeverity, ZeroHallucinationRetrievalResult)
- .guard: ZeroHallucinationPromptGuard
- .evaluator: MemoryStateAssertionEvaluator

[OUTPUT]
- Package exports for zero-hallucination retrieval protocol
"""

from myrm_agent_harness.toolkits.memory.zero_hallucination.evaluator import (
    MemoryStateAssertionEvaluator,
)
from myrm_agent_harness.toolkits.memory.zero_hallucination.guard import (
    ZeroHallucinationPromptGuard,
)
from myrm_agent_harness.toolkits.memory.zero_hallucination.models import (
    MemoryFactItem,
    MemoryRetrievalState,
    RetrievalErrorSeverity,
    ZeroHallucinationRetrievalResult,
)

__all__ = [
    "MemoryFactItem",
    "MemoryRetrievalState",
    "MemoryStateAssertionEvaluator",
    "RetrievalErrorSeverity",
    "ZeroHallucinationPromptGuard",
    "ZeroHallucinationRetrievalResult",
]
