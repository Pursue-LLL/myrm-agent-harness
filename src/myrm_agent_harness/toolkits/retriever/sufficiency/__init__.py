"""Retrieval Sufficiency Guard (RSG) — evaluate retrieval quality before answering.

[INPUT]
- .evaluator::evaluate_sufficiency (POS: evaluate retrieval adequacy)
- .types::SufficiencyConfig, SufficiencyVerdict (POS: evaluation config and verdict dataclass)

[OUTPUT]
- evaluate_sufficiency: async function that evaluates whether retrieved snippets are sufficient
- SufficiencyConfig: dataclass holding configuration for sufficiency evaluation
- SufficiencyVerdict: dataclass holding the verdict of retrieval sufficiency evaluation

[POS]
Retrieval Sufficiency Guard 模块入口。提供检索后质量评估与判定结果导出。
"""

from .evaluator import evaluate_sufficiency
from .types import SufficiencyConfig, SufficiencyVerdict

__all__ = [
    "SufficiencyConfig",
    "SufficiencyVerdict",
    "evaluate_sufficiency",
]
