"""
[INPUT]: Tool output bytes, token metrics, session event records, and role view filters.
[OUTPUT]: Immutable ToolSavingsRecord, SessionSavingsAudit, EngineeringSignalItem, and RoleEngineeringInsightReport.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/context_optimization/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class EngineeringSignalPattern(str, Enum):
    HIGH_RETRY_CHURN = "HIGH_RETRY_CHURN"          # 高频重试死循环消耗
    TOOL_OUTPUT_BLOAT = "TOOL_OUTPUT_BLOAT"        # 工具原始输出剧烈膨胀（需强力拦截截断）
    LONG_BLOCKING_IO = "LONG_BLOCKING_IO"          # 长耗时阻塞等待 (网络/外部I/O瓶颈)
    CACHE_STARVATION = "CACHE_STARVATION"          # 缓存未命中率异常高 (前缀抖动)
    SUBAGENT_DEADLOCK = "SUBAGENT_DEADLOCK"        # 并发子智能体依赖死锁或互斥等待
    FLAKY_ENVIRONMENT = "FLAKY_ENVIRONMENT"        # 外部沙箱或依赖环境间歇性报错
    COST_ANOMALY = "COST_ANOMALY"                  # 单次工具调用花费远超基线均值


class RoleInsightView(str, Enum):
    CTO = "CTO"
    EM = "EM"
    FINOPS = "FINOPS"
    DEVOPS = "DEVOPS"


@dataclass(frozen=True)
class ToolSavingsRecord:
    session_id: str
    tool_name: str
    original_bytes: int
    optimized_bytes: int
    original_tokens: int
    optimized_tokens: int
    saved_tokens: int
    savings_rate_pct: float
    cost_saved_usd: float
    cost_saved_cny: float
    cache_hit: bool
    recorded_at: str


@dataclass(frozen=True)
class ToolSavingsSummary:
    tool_name: str
    total_calls: int
    total_original_tokens: int
    total_optimized_tokens: int
    total_saved_tokens: int
    average_savings_rate_pct: float
    total_cost_saved_usd: float
    total_cost_saved_cny: float
    cache_hit_rate_pct: float


@dataclass(frozen=True)
class SessionSavingsAudit:
    session_id: str
    total_tool_calls: int
    total_original_tokens: int
    total_optimized_tokens: int
    total_saved_tokens: int
    overall_savings_rate_pct: float
    total_cost_saved_usd: float
    total_cost_saved_cny: float
    tool_breakdown: List[ToolSavingsSummary]
    summary_headline: str


@dataclass(frozen=True)
class EngineeringSignalItem:
    signal_pattern: EngineeringSignalPattern
    severity: str  # HIGH | MEDIUM | LOW
    target_entity: str  # tool_name, agent_id, or step_name
    detected_metric_value: float
    metric_threshold: float
    root_cause_explanation: str
    actionable_remediation: str


@dataclass(frozen=True)
class RoleEngineeringInsightReport:
    role: RoleInsightView
    evaluated_sessions_count: int
    total_saved_tokens_aggregate: int
    total_cost_saved_usd_aggregate: float
    top_efficiency_tools: List[str]
    identified_engineering_signals: List[EngineeringSignalItem]
    primary_bottleneck_summary: str
