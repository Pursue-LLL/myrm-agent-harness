"""[INPUT] Agent interaction logs, skill execution timings, and HITL bottleneck metrics.
[OUTPUT] Immutable data structures for Custom Agent Insights (intent clusters, skill funnel, and HITL ROI).
[POS] myrm_agent_harness.observability.agent_insights.models

Defines the core data models for custom agent operational observability:
1. Intent & scenario cluster distributions
2. Skill execution health & latency funnel
3. HITL approval bottleneck and token output ROI
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class SkillExecutionStatus(str, Enum):
    """Execution status of an individual skill or tool call."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class AgentIntentCluster:
    """Clustered business intent or user job-to-be-done for an agent."""

    intent_category: str
    sample_utterance: str
    request_count: int
    share_pct: float

    def to_dict(self) -> dict[str, str | int | float]:
        return {
            "intent_category": self.intent_category,
            "sample_utterance": self.sample_utterance,
            "request_count": self.request_count,
            "share_pct": self.share_pct,
        }


@dataclass(frozen=True)
class AgentSkillHealthMetric:
    """Funnel metrics and execution health for a skill mounted to an agent."""

    skill_name: str
    total_calls: int
    success_rate_pct: float
    avg_latency_ms: float
    p95_latency_ms: float
    top_error_reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, str | int | float | list[str]]:
        return {
            "skill_name": self.skill_name,
            "total_calls": self.total_calls,
            "success_rate_pct": self.success_rate_pct,
            "avg_latency_ms": self.avg_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "top_error_reasons": list(self.top_error_reasons),
        }


@dataclass(frozen=True)
class AgentHitlBottleneckMetric:
    """Human-in-the-loop intervention friction and approval delay metrics."""

    total_tasks: int
    hitl_intercepted_tasks: int
    hitl_interception_rate_pct: float
    avg_approval_wait_seconds: float
    token_roi_ratio: float  # Deliverables or artifacts generated per 10k tokens

    def to_dict(self) -> dict[str, int | float]:
        return {
            "total_tasks": self.total_tasks,
            "hitl_intercepted_tasks": self.hitl_intercepted_tasks,
            "hitl_interception_rate_pct": self.hitl_interception_rate_pct,
            "avg_approval_wait_seconds": self.avg_approval_wait_seconds,
            "token_roi_ratio": self.token_roi_ratio,
        }


@dataclass(frozen=True)
class CustomAgentInsightsSnapshot:
    """Aggregated operational insights snapshot for a specific custom agent."""

    agent_id: str
    time_window_days: int
    total_interactions: int
    total_tokens_consumed: int
    intent_clusters: tuple[AgentIntentCluster, ...] = field(default_factory=tuple)
    skill_funnel: tuple[AgentSkillHealthMetric, ...] = field(default_factory=tuple)
    hitl_metrics: AgentHitlBottleneckMetric = field(
        default_factory=lambda: AgentHitlBottleneckMetric(0, 0, 0.0, 0.0, 1.0)
    )
    generated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, str | int | float | list[dict[str, str | int | float]] | dict[str, int | float]]:
        return {
            "agent_id": self.agent_id,
            "time_window_days": self.time_window_days,
            "total_interactions": self.total_interactions,
            "total_tokens_consumed": self.total_tokens_consumed,
            "intent_clusters": [c.to_dict() for c in self.intent_clusters],
            "skill_funnel": [s.to_dict() for s in self.skill_funnel],
            "hitl_metrics": self.hitl_metrics.to_dict(),
            "generated_at_ms": self.generated_at_ms,
        }
