"""[INPUT]
- collections.Counter, typing (Standard library algorithms)
- myrm_agent_harness.observability.thought_telemetry.models::{RunawayReason}

[OUTPUT]
- CoTRunawayGuard: 思维链死循环与失控熔断守卫

[POS]
myrm_agent_harness.observability.thought_telemetry.runaway_guard — 实时检测长思考模型隐蔽死循环与发散失控。
"""

from __future__ import annotations

from collections import Counter

from myrm_agent_harness.observability.thought_telemetry.models import RunawayReason

# 默认安全防护门限
DEFAULT_MAX_THOUGHT_TOKENS = 4096
DEFAULT_REPETITION_THRESHOLD = 0.42
DEFAULT_MIN_CHARS_FOR_ANALYSIS = 180


class CoTRunawayGuard:
    """思考链死循环与发散度熔断守护器。

    直击长推理模型在思维链中出现无限循环复读、死锁验证或无意义发散导致燃烧海量 Token 的痛点。
    """

    def __init__(
        self,
        *,
        max_budget_tokens: int = DEFAULT_MAX_THOUGHT_TOKENS,
        repetition_threshold: float = DEFAULT_REPETITION_THRESHOLD,
        min_chars_for_analysis: int = DEFAULT_MIN_CHARS_FOR_ANALYSIS,
    ) -> None:
        self.max_budget_tokens = max_budget_tokens
        self.repetition_threshold = repetition_threshold
        self.min_chars_for_analysis = min_chars_for_analysis

    def check_runaway(
        self,
        thought_text: str,
        token_count: int,
    ) -> tuple[bool, RunawayReason, float, str | None]:
        """分析当前思维流文本，判定是否陷入死循环或超出安全上限。

        Returns:
            (is_runaway, reason, repetition_ratio, soft_interrupt_hint)
        """
        # 1. 预算上限熔断
        if token_count >= self.max_budget_tokens:
            return (
                True,
                RunawayReason.EXCESSIVE_LENGTH,
                0.0,
                "思考 Token 超过安全预算上限，已触发软中断，请立即输出最终结论。",
            )

        # 文本过短时不执行重计算
        clean_text = thought_text.strip()
        if len(clean_text) < self.min_chars_for_analysis:
            return False, RunawayReason.NONE, 0.0, None

        # 2. 滑动窗口 N-gram 重复率分析（基于 4-gram 字符切片）
        # 选取最近的尾部窗口（最近 600 字符，死循环往往在尾部高频爆发）
        tail_window = clean_text[-700:] if len(clean_text) > 700 else clean_text
        n = 4
        if len(tail_window) < n * 3:
            return False, RunawayReason.NONE, 0.0, None

        ngrams = [tail_window[i : i + n] for i in range(len(tail_window) - n + 1)]
        total_ngrams = len(ngrams)
        unique_ngrams = len(set(ngrams))

        if total_ngrams == 0:
            return False, RunawayReason.NONE, 0.0, None

        repetition_ratio = 1.0 - (unique_ngrams / total_ngrams)

        # 检查最高频 n-gram 是否出现异常过密
        counter = Counter(ngrams)
        most_common_freq = counter.most_common(1)[0][1] if counter else 0
        density = most_common_freq / total_ngrams

        if repetition_ratio >= self.repetition_threshold or density >= 0.18:
            return (
                True,
                RunawayReason.NGRAM_REPETITION_LOOP,
                repetition_ratio,
                "检测到思维链出现高频死循环复读 (Loop Detected)，请立即停止推演并直接回答。",
            )

        return False, RunawayReason.NONE, repetition_ratio, None
