"""
[INPUT]: Raw LLM usage dictionaries, provider identifiers, and model naming tags.
[OUTPUT]: Immutable NormalizedTokenUsageSnapshot, ReasoningInclusionPolicy, and InvariantCheckResult contracts.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/reasoning_semantics/models.py
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ReasoningInclusionPolicy(str, Enum):
    INCLUDED_IN_COMPLETION = "INCLUDED_IN_COMPLETION"  # OpenAI, Anthropic, DeepSeek: completion_tokens 已包含 reasoning
    STANDALONE_OUTPUT = "STANDALONE_OUTPUT"            # 特殊自定义网关: completion_tokens 仅代表 visible content，需显式合并
    INDEPENDENT_BILLING = "INDEPENDENT_BILLING"        # 特殊模型: 推理 Token 实行单独单价计费


@dataclass(frozen=True)
class NormalizedTokenUsageSnapshot:
    prompt_tokens: int
    completion_tokens: int  # 权威总输出 Token 数 (必含 reasoning_tokens)
    reasoning_tokens: int   # 从属子集 Token 数 (reasoning_tokens ⊆ completion_tokens)
    visible_content_tokens: int  # 净可见内容 Token 数 = completion_tokens - reasoning_tokens
    total_tokens: int  # 不变量: total_tokens == prompt_tokens + completion_tokens (零二次重复累加)
    cost_usd: float
    is_zero_double_counted: bool  # 经过归一化断言确认，严防双重计费
    raw_provider: str
    policy_applied: ReasoningInclusionPolicy
    normalized_at: str


@dataclass(frozen=True)
class InvariantCheckResult:
    is_valid: bool
    violation_type: Optional[str]  # e.g. "DOUBLE_COUNTING_TOTAL", "REASONING_EXCEEDS_COMPLETION", None
    diagnostic_warning: Optional[str]
    corrected_snapshot: Optional[NormalizedTokenUsageSnapshot]
