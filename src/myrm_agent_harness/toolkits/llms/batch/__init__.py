"""Batch LLM utilities.

Pure, agent-agnostic fan-out engine. The GUI-facing agent tool that adapts this
engine (Artifact Vault spillover, progress sink, cancellation) lives in
``agent.meta_tools.llm_map`` to keep this toolkit layer free of reverse deps.

[INPUT]
- .llm_map::llm_map, LlmMapItemResult, LlmMapReport, LlmMapProgress

[OUTPUT]
- llm_map / LlmMapItemResult / LlmMapReport / LlmMapProgress: the fan-out engine

[POS]
Batch LLM utilities. Houses the lightweight ``llm_map`` fan-out primitive —
bulk per-item LLM work without sub-agent overhead.
"""

from .llm_map import (
    DEFAULT_ITEM_TIMEOUT_S,
    DEFAULT_MAX_CONCURRENCY,
    MAX_CONCURRENCY_HARD_CAP,
    MAX_ITEMS_HARD_CAP,
    LlmMapItemResult,
    LlmMapProgress,
    LlmMapReport,
    llm_map,
)

__all__ = [
    "DEFAULT_ITEM_TIMEOUT_S",
    "DEFAULT_MAX_CONCURRENCY",
    "MAX_CONCURRENCY_HARD_CAP",
    "MAX_ITEMS_HARD_CAP",
    "LlmMapItemResult",
    "LlmMapProgress",
    "LlmMapReport",
    "llm_map",
]
