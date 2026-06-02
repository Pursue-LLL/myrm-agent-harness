"""Memory Retrieval Eval — dataset-driven recall quality evaluation.

Public API:
- Types: MemoryRetrievalEvalCase, MemoryRetrievalCaseResult, MemoryRetrievalEvalSummary
- Protocol: MemoryRetrievalAdapter
- Runner: MemoryRetrievalEvalRunner
- Loader: load_eval_cases
"""

from .protocols import (
    MemoryRetrievalAdapter,
    MemoryRetrievalCaseResult,
    MemoryRetrievalCategorySummary,
    MemoryRetrievalEvalCase,
    MemoryRetrievalEvalSummary,
)
from .runner import MemoryRetrievalEvalRunner, load_eval_cases

__all__ = [
    "MemoryRetrievalAdapter",
    "MemoryRetrievalCaseResult",
    "MemoryRetrievalCategorySummary",
    "MemoryRetrievalEvalCase",
    "MemoryRetrievalEvalRunner",
    "MemoryRetrievalEvalSummary",
    "load_eval_cases",
]
