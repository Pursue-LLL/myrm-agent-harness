"""Domain models and types for Conversational Multi-Specialist Summoning & Context Aggregation (Item 54).

Defines specialist domains, profiles, summon requests, execution records,
and structured aggregation card contracts for returning specialist deliverables
cleanly to the primary chat stream.

[INPUT]
- __future__
- dataclasses
- enum

[OUTPUT]
- SpecialistDomain
- SummonTriggerSource
- AggregationCardType
- SummonExecutionStatus
- SpecialistProfile
- SummonRequest
- StructuredAggregationCard
- SummonSessionExecution

[POS]
Domain models and types for Conversational Multi-Specialist Summoning & Context Aggregation (Item 54).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SpecialistDomain(StrEnum):
    """Vertical domain categories supported by conversational specialists."""

    COPYWRITING_POLISH = "copywriting_polish"  # 去AI味 / 文案润色
    VISUAL_DESIGN = "visual_design"  # 视觉 / 配图设计
    CODE_AUDIT = "code_audit"  # 代码 / 安全审计
    MARKET_RESEARCH = "market_research"  # 竞品 / 市场调研
    DATA_ANALYSIS = "data_analysis"  # 数据分析 / 指标测算


class SummonTriggerSource(StrEnum):
    """Origin of a specialist invocation."""

    EXPLICIT_MENTION = "explicit_mention"  # 用户在输入框通过 @专家名 召唤
    INTENT_DETECTION = "intent_detection"  # 主 Orchestrator 智能感知子任务属性推荐


class AggregationCardType(StrEnum):
    """Artifact classification of the deliverable returned by the specialist."""

    TEXT_POLISH = "text_polish"
    VISUAL_SPEC = "visual_spec"
    AUDIT_VERDICT = "audit_verdict"
    RESEARCH_REPORT = "research_report"
    DATA_CHART = "data_chart"


class SummonExecutionStatus(StrEnum):
    """Lifecycle status of a specialist isolated execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class SpecialistProfile:
    """Specification of a specialist agent eligible for dynamic conversational summoning."""

    specialist_id: str
    name: str
    mention_tag: str  # e.g., "@去AI味专家", "@视觉专家"
    domain: SpecialistDomain
    description: str
    system_prompt_addon: str
    suggested_keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SummonRequest:
    """Invocation request to dispatch a task to a specialized agent in an isolated child session."""

    summon_id: str
    chat_id: str
    specialist_id: str
    trigger_source: SummonTriggerSource
    instruction: str
    parent_context_slice: str = ""


@dataclass(frozen=True)
class StructuredAggregationCard:
    """Standardized structured card contract bridging specialist deliverables back to parent stream."""

    card_id: str
    summon_id: str
    specialist_id: str
    specialist_name: str
    card_type: AggregationCardType
    headline: str
    deliverable_payload: str
    artifacts: list[str] = field(default_factory=list)
    created_at: float = 0.0


@dataclass
class SummonSessionExecution:
    """Execution state container for an isolated specialist run."""

    summon_id: str
    chat_id: str
    specialist_id: str
    status: SummonExecutionStatus
    request: SummonRequest
    aggregation_card: StructuredAggregationCard | None = None
    execution_seconds: float = 0.0
    error_message: str | None = None
