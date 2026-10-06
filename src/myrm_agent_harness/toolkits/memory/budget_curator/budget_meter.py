# [POS] myrm_agent_harness/toolkits/memory/budget_curator/budget_meter.py
# [INPUT] ManagedMemoryItem, MemoryBudgetSpec, MemoryBudgetStatus from .types
# [OUTPUT] MemoryBudgetMeter (声明式记忆预算计量器与标头渲染器)

"""声明式记忆上下文预算计量器，渲染可视化预算仪表盘标头并监控容量水位。"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.budget_curator.types import (
    ManagedMemoryItem,
    MemoryBudgetSpec,
    MemoryBudgetStatus,
)


class MemoryBudgetMeter:
    """记忆字符/Token 与槽位预算计量器。"""

    def __init__(self, spec: MemoryBudgetSpec | None = None) -> None:
        self.spec = spec or MemoryBudgetSpec()

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """轻量自适应估算文本消耗的 Token 数量。"""
        if not text:
            return 0
        # 统计中文字符与英文字词
        chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", text))
        non_chinese = re.sub(r"[\u4e00-\u9fa5]", "", text).strip()
        words = len(re.findall(r"\w+", non_chinese))
        other_chars = max(0, len(non_chinese) - words * 3)
        # 中文约 1 字 1 token，英文约 1 词 1.3 token
        estimated = chinese_chars + int(words * 1.3) + int(other_chars * 0.3)
        return max(1, estimated)

    def evaluate_budget(
        self, items: Sequence[ManagedMemoryItem]
    ) -> MemoryBudgetStatus:
        """计算给定记忆列表的实时预算状态。"""
        used_tokens = sum(item.token_count for item in items)
        used_slots = len(items)

        token_pct = (
            round((used_tokens / self.spec.max_tokens) * 100.0, 1)
            if self.spec.max_tokens > 0
            else 0.0
        )
        slot_pct = (
            round((used_slots / self.spec.max_slots) * 100.0, 1)
            if self.spec.max_slots > 0
            else 0.0
        )

        is_overflow = (
            used_tokens > self.spec.max_tokens or used_slots > self.spec.max_slots
        )
        is_warning = (
            token_pct >= self.spec.warning_threshold_pct
            or slot_pct >= self.spec.warning_threshold_pct
        )

        header_slice = self.render_budget_header(
            used_tokens=used_tokens,
            used_slots=used_slots,
            token_pct=token_pct,
            is_overflow=is_overflow,
        )

        return MemoryBudgetStatus(
            used_tokens=used_tokens,
            max_tokens=self.spec.max_tokens,
            token_usage_pct=token_pct,
            used_slots=used_slots,
            max_slots=self.spec.max_slots,
            slot_usage_pct=slot_pct,
            is_warning=is_warning,
            is_overflow=is_overflow,
            budget_header_slice=header_slice,
        )

    def render_budget_header(
        self,
        used_tokens: int,
        used_slots: int,
        token_pct: float,
        is_overflow: bool = False,
    ) -> str:
        """渲染自包含提示词预算标头。"""
        status_tag = ""
        if is_overflow:
            status_tag = " [EXCEEDED - CLEANUP REQUIRED]"
        elif token_pct >= self.spec.warning_threshold_pct:
            status_tag = " [WARNING - NEAR CAPACITY]"

        return (
            f"# USER PROFILE & MEMORIES [Budget: {token_pct:.0f}%, "
            f"{used_tokens}/{self.spec.max_tokens} tokens | "
            f"Slots: {used_slots}/{self.spec.max_slots}]{status_tag}"
        )
