"""Targeted Experience Auto-Recall Trigger with Multi-Turn Dedup and Fail-Open Reranking.

[INPUT]
- toolkits.memory.auto_recall.fail_open_reranker::FailOpenReranker (POS: Fail-open reranker wrapper
  guaranteeing non-blocking fallback on missing keys or timeouts.)
- toolkits.memory.auto_recall.recall_gate::ExperienceRecallGate (POS: Facade orchestrator coordinating
  trigger classification, dedup, and fail-open reranking.)
- toolkits.memory.auto_recall.sliding_window_dedup::SlidingWindowDedupGate (POS: Sliding window
  deduplication gate to suppress redundant memory injection across turns.)
- toolkits.memory.auto_recall.trigger_classifier::ExperienceRecallTriggerClassifier (POS: Deterministic and
  lightweight classifier for 5 high-risk recall trigger scenarios.)
- toolkits.memory.auto_recall.types::AutoRecallDecision, RecallCandidate, RecallGateConfig,
  RecallTriggerType, RerankerStatus (POS: Type definitions and contracts for Targeted Experience Auto-Recall
  Engine.)

[OUTPUT]
- Package facade re-exporting 9 public names: AutoRecallDecision, ExperienceRecallGate,
  ExperienceRecallTriggerClassifier, FailOpenReranker, RecallCandidate, RecallGateConfig, RecallTriggerType,
  RerankerStatus, SlidingWindowDedupGate

[POS]
Targeted Experience Auto-Recall Trigger with Multi-Turn Dedup and Fail-Open Reranking.
"""

from __future__ import annotations

from .fail_open_reranker import FailOpenReranker
from .recall_gate import ExperienceRecallGate
from .sliding_window_dedup import SlidingWindowDedupGate
from .tool import (
    AutoRecallCandidateInput,
    AutoRecallTriggerInput,
    create_auto_recall_evaluator_tool,
)
from .trigger_classifier import ExperienceRecallTriggerClassifier
from .types import (
    AutoRecallDecision,
    RecallCandidate,
    RecallGateConfig,
    RecallTriggerType,
    RerankerStatus,
)

__all__ = [
    "AutoRecallCandidateInput",
    "AutoRecallDecision",
    "AutoRecallTriggerInput",
    "ExperienceRecallGate",
    "ExperienceRecallTriggerClassifier",
    "FailOpenReranker",
    "RecallCandidate",
    "RecallGateConfig",
    "RecallTriggerType",
    "RerankerStatus",
    "SlidingWindowDedupGate",
    "create_auto_recall_evaluator_tool",
]

