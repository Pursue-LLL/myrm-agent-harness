"""Strongly-typed data contracts for model-tier adaptive topology pruning.

[INPUT]
- typing::Literal
- pydantic::BaseModel, Field

[OUTPUT]
- ModelIntelligenceTier: 3-level model capability hierarchy.
- PruningStrategy: Operational mode for pruning decisions.
- PruningDecisionKind: Final topological structure recommendation.
- TaskComplexityLevel: Assessed task difficulty and scope.
- TopologyPruningEvaluation: Complete pruning assessment record.

[POS]
Data contracts for DSH-style adaptive orchestration topology pruning and folding.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

ModelIntelligenceTier = Literal[
    "tier_1_sota_reasoning",  # SOTA Long Reasoning (DeepSeek-R1/V4-Pro, Claude 3.7 Sonnet, GPT-5/o1/o3)
    "tier_2_strong_base",      # Strong Base models (Claude 3.5 Haiku, GPT-4o-mini, Qwen 2.5 32B/72B)
    "tier_3_fast_light",       # Fast lightweight models (Qwen 7B, Llama 8B, local tiny models)
]

PruningStrategy = Literal[
    "auto",               # Automatically fold or fan-out based on model tier and task complexity
    "always_multi_agent", # Force multi-agent fan-out regardless of model tier
    "direct_only",        # Force direct single-agent execution without subagent spawn
]

PruningDecisionKind = Literal[
    "direct_execution",   # Folded: Single-agent direct deep reasoning execution
    "fanout_multi_agent", # Kept: Full multi-subagent delegation topology
    "hybrid_folded",      # Partial folding: Main task direct, auxiliary verifier only
]

TaskComplexityLevel = Literal[
    "low",                # Minor edits, single file changes, lookups
    "medium",             # Refactor across 2-3 files, bug fix with regression test
    "high",               # System design, cross-repository features, multi-step migration
    "extreme",            # Large architectural rewrite, high security audit
]


class TopologyPruningEvaluation(BaseModel):
    """Assessment outcome of model capability-aware topology pruning."""

    decision: PruningDecisionKind
    model_name: str
    model_tier: ModelIntelligenceTier
    strategy: PruningStrategy
    task_complexity: TaskComplexityLevel
    is_folded: bool
    rationale: str
    planned_subtasks_count: int
    executed_subtasks_count: int
    estimated_saved_turns: int
    estimated_saved_tokens: int
    evaluated_at: float = Field(default_factory=time.time)
