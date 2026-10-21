"""
[INPUT]: Raw HTTP response headers, model configs, subagent tasks, and token budgets.
[OUTPUT]: Immutable quota snapshots, proactive pacing decisions, and subagent concurrency slices.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/rate_limit_governor/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class PacingAction(str, Enum):
    IMMEDIATE_PASS = "IMMEDIATE_PASS"  # 正常放行
    MICRO_SLEEP_PACED = "MICRO_SLEEP_PACED"  # 前置微延迟平滑整形 (200~500ms)
    QUEUE_WAIT = "QUEUE_WAIT"  # 严重接近限额，排队等待窗口重置
    FALLBACK_DOWNGRADE = "FALLBACK_DOWNGRADE"  # 自动推荐降级至 Fast/Free Tier


@dataclass(frozen=True)
class ProviderQuotaHeaderSnapshot:
    model_name: str
    remaining_tokens: Optional[int] = None
    reset_tokens_seconds: Optional[float] = None
    remaining_requests: Optional[int] = None
    reset_requests_seconds: Optional[float] = None
    retry_after_seconds: Optional[float] = None
    extracted_at: str = ""


@dataclass(frozen=True)
class ModelRateLimitConfig:
    model_name: str
    max_rpm: int = 60
    max_tpm: int = 100_000
    safe_watermark_pct: float = 85.0  # 超过 85% 触发主动整形平峰


@dataclass(frozen=True)
class QuotaPacingDecision:
    action: PacingAction
    delay_ms: int
    current_tpm_usage: int
    max_tpm_limit: int
    tpm_watermark_pct: float
    current_rpm_usage: int
    max_rpm_limit: int
    reason: str
    target_model_or_fallback: str


@dataclass(frozen=True)
class SubagentQuotaSlice:
    workspace_id: str
    subagent_id: str
    allocated_tpm_share: int
    consumed_tokens_in_window: int
    remaining_tokens_in_window: int
    is_throttled: bool


@dataclass(frozen=True)
class GovernorLiveStatus:
    model_name: str
    tpm_watermark_pct: float
    rpm_watermark_pct: float
    smoothed_request_count: int
    prevented_429_count: int
    active_subagent_slices_count: int
    status_label: str
