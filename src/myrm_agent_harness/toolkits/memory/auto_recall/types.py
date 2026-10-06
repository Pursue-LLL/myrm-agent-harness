# [POS] toolkits/memory/auto_recall/types.py
# [INPUT] None
# [OUTPUT] RecallTriggerType, RerankerStatus, RecallCandidate, AutoRecallDecision, RecallGateConfig

"""Type definitions and contracts for Targeted Experience Auto-Recall Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RecallTriggerType(StrEnum):
    """High-risk sensitive lifecycle triggers that activate experience recall."""

    TASK_START = "task_start"  # Initialization of a new task/goal
    SKILL_LOAD = "skill_load"  # Dynamic loading or invocation of an external skill
    SUBAGENT_START = "subagent_start"  # Delegation or spawning of a subagent
    WRITE_PREFLIGHT = "write_preflight"  # Prior to modifying disk, configs, or state
    CRON_START = "cron_start"  # Autonomous cron or heartbeat schedule triggering
    NONE = "none"  # Casual chat, read-only queries, or low-risk interaction


class RerankerStatus(StrEnum):
    """Execution status and fail-open state of the reranking stage."""

    APPLIED = "applied"  # Successfully reranked using neural/voyage model
    RERANKER_SKIPPED = "reranker_skipped"  # Key missing; transparently skipped without error
    TIMED_OUT = "timed_out"  # Latency exceeded SLA; gracefully fallen back to rough rank
    FAILED_OPEN = "failed_open"  # Unexpected exception caught and suppressed fail-open


@dataclass(frozen=True)
class RecallCandidate:
    """An experience or memory candidate retrieved from the rough storage tier."""

    memory_id: str
    content: str
    initial_score: float = 0.5
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class AutoRecallDecision:
    """The aggregate audit decision produced by ExperienceRecallGate."""

    triggered: bool
    trigger_type: RecallTriggerType
    candidates_pre_dedup: int
    candidates_post_dedup: int
    injected_candidates: list[RecallCandidate]
    reranker_status: RerankerStatus
    audit_reason: str


@dataclass(frozen=True)
class RecallGateConfig:
    """Configuration governing auto-recall triggers, dedup windows, and fail-open behavior."""

    dedup_turns: int = 5
    reranker_timeout_ms: float = 800.0
    min_recall_score: float = 0.5
    max_injected_items: int = 3
    api_key_env_var: str = "RERANKER_API_KEY"
