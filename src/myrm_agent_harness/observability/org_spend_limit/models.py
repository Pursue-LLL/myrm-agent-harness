"""
[INPUT]: Organization identifiers, query labels, surface tags, and monthly budget limits.
[OUTPUT]: Immutable SpendGovernorDecision verdicts, QuerySpendLabel contracts, and IdentSpendAttribution reports.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/org_spend_limit/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class BillingScope(str, Enum):
    ORG_SHARED = "ORG_SHARED"          # 群聊/频道协同：计入组织公摊账本
    PERSONAL_DM = "PERSONAL_DM"        # 私聊直接会话：记入个人账户


class SpendSurface(str, Enum):
    CHANNEL = "CHANNEL"                # 群组/频道 (Slack/Lark/Discord)
    DIRECT_MESSAGE = "DIRECT_MESSAGE"  # 私信 1-on-1
    REST_API = "REST_API"              # 自动化 API 调用
    AUTOMATED_CI = "AUTOMATED_CI"      # 持续集成管道自动化任务


class GovernorAction(str, Enum):
    ALLOW = "ALLOW"                                    # 正常放行
    WARN_APPROACHING = "WARN_APPROACHING"              # 达到 80% 软上限告警，顺畅放行
    CIRCUIT_BREAKER_BLOCKED = "CIRCUIT_BREAKER_BLOCKED"# 触碰 100% 硬限额熔断刹车


@dataclass(frozen=True)
class QuerySpendLabel:
    org_id: str
    surface: SpendSurface
    billing_scope: BillingScope
    session_id: str
    requesting_user_id: str  # 对应 ident:<id> 身份命名空间
    query_tags: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SpendLimitConfig:
    org_id: str
    monthly_budget_usd: float = 100.0
    soft_warn_watermark_pct: float = 80.0
    hard_block_limit_usd: float = 100.0
    is_circuit_breaker_enabled: bool = True


@dataclass(frozen=True)
class OrgMonthlySpendRecord:
    record_id: str
    org_id: str
    label: QuerySpendLabel
    tokens_consumed: int
    cost_usd: float
    recorded_at: str


@dataclass(frozen=True)
class SpendGovernorDecision:
    action: GovernorAction
    current_spend_usd: float
    monthly_budget_usd: float
    utilization_pct: float
    reason: str
    is_blocked: bool


@dataclass(frozen=True)
class IdentSpendAttribution:
    requesting_user_id: str
    total_calls_count: int
    total_tokens: int
    total_spend_usd: float
    surfaces_breakdown: Dict[str, float]
    primary_surface: str
