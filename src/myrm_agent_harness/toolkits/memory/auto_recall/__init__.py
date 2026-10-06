# [POS] toolkits/memory/auto_recall/__init__.py
# [INPUT] types, trigger_classifier, sliding_window_dedup, fail_open_reranker, recall_gate
# [OUTPUT] Public exports for auto_recall package

"""Targeted Experience Auto-Recall Trigger with Multi-Turn Dedup and Fail-Open Reranking."""

from __future__ import annotations

from .fail_open_reranker import FailOpenReranker
from .recall_gate import ExperienceRecallGate
from .sliding_window_dedup import SlidingWindowDedupGate
from .trigger_classifier import ExperienceRecallTriggerClassifier
from .types import (
    AutoRecallDecision,
    RecallCandidate,
    RecallGateConfig,
    RecallTriggerType,
    RerankerStatus,
)

__all__ = [
    "AutoRecallDecision",
    "ExperienceRecallGate",
    "ExperienceRecallTriggerClassifier",
    "FailOpenReranker",
    "RecallCandidate",
    "RecallGateConfig",
    "RecallTriggerType",
    "RerankerStatus",
    "SlidingWindowDedupGate",
]
