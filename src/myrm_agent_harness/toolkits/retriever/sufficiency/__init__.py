"""Retrieval Sufficiency Guard (RSG) — evaluate retrieval quality before answering.

Public API:
- evaluate_sufficiency(): Evaluate whether retrieval results adequately cover a query.
- SufficiencyVerdict: Evaluation result dataclass.
- SufficiencyConfig: Configuration for activation and behavior.
"""

from .evaluator import evaluate_sufficiency
from .types import SufficiencyConfig, SufficiencyVerdict

__all__ = [
    "SufficiencyConfig",
    "SufficiencyVerdict",
    "evaluate_sufficiency",
]
