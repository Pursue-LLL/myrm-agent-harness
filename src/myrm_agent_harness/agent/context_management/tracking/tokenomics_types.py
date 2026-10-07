"""Data types and contracts for Tokenomics Savings Tracker and Live Cost HUD.

[INPUT]
- dataclasses::dataclass, field (POS: Python 数据类标准库)
- typing::Literal (POS: Python 类型提示)

[OUTPUT]
- ModelPricingTier: 模型百万 Token 费率数据类
- SavingsEvent: 单次压缩与紧凑化节省明细事件
- TokenSavingsHudSummary: 会话与任务级 Token 经济学 HUD 看板摘要
- DEFAULT_MODEL_PRICING_CATALOG: 主流前沿大模型预置费率目录
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ModelPricingTier:
    """Pricing configuration per million tokens (USD)."""

    model_pattern: str
    input_cost_per_million: float
    output_cost_per_million: float
    cache_read_cost_per_million: float


# Industry benchmark pricing matrix (USD per 1M tokens)
DEFAULT_MODEL_PRICING_CATALOG: dict[str, ModelPricingTier] = {
    "deepseek-v3": ModelPricingTier(
        model_pattern="deepseek-v3",
        input_cost_per_million=0.27,
        output_cost_per_million=1.10,
        cache_read_cost_per_million=0.07,
    ),
    "deepseek-r1": ModelPricingTier(
        model_pattern="deepseek-r1",
        input_cost_per_million=0.55,
        output_cost_per_million=2.19,
        cache_read_cost_per_million=0.14,
    ),
    "claude-3-5-sonnet": ModelPricingTier(
        model_pattern="claude-3-5-sonnet",
        input_cost_per_million=3.00,
        output_cost_per_million=15.00,
        cache_read_cost_per_million=0.30,
    ),
    "claude-3-5-haiku": ModelPricingTier(
        model_pattern="claude-3-5-haiku",
        input_cost_per_million=0.80,
        output_cost_per_million=4.00,
        cache_read_cost_per_million=0.08,
    ),
    "gpt-4o": ModelPricingTier(
        model_pattern="gpt-4o",
        input_cost_per_million=2.50,
        output_cost_per_million=10.00,
        cache_read_cost_per_million=1.25,
    ),
    "gpt-4o-mini": ModelPricingTier(
        model_pattern="gpt-4o-mini",
        input_cost_per_million=0.15,
        output_cost_per_million=0.60,
        cache_read_cost_per_million=0.075,
    ),
    "qwen-2.5": ModelPricingTier(
        model_pattern="qwen-2.5",
        input_cost_per_million=0.30,
        output_cost_per_million=1.20,
        cache_read_cost_per_million=0.08,
    ),
    "default": ModelPricingTier(
        model_pattern="default",
        input_cost_per_million=1.00,
        output_cost_per_million=3.00,
        cache_read_cost_per_million=0.20,
    ),
}


@dataclass(frozen=True, slots=True)
class SavingsEvent:
    """Single diagnostic record of token compaction savings."""

    event_id: str
    timestamp: float
    operator_name: str
    raw_tokens: int
    compacted_tokens: int
    saved_tokens: int
    saved_ratio: float
    model_name: str
    estimated_cost_saved_usd: float
    cached_tokens: int = 0
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TokenSavingsHudSummary:
    """Aggregated live diagnostic view for Frontend HUD & Desktop dashboards."""

    session_id: str
    total_raw_tokens: int
    total_compacted_tokens: int
    total_saved_tokens: int
    overall_savings_percentage: float
    total_cost_saved_usd: float
    total_prompt_cache_hits_tokens: int
    operator_breakdown: dict[str, int]
    formatted_hud_badge: str
    recent_events_count: int
