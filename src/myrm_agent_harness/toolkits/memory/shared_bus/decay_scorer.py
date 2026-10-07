"""命中频次正向强化与时间半衰期衰减联合打分器，实现常用常新、长期未用平滑遗忘。

[INPUT]
- toolkits.memory.shared_bus.types::ReinforcedDecayConfig, ScoredMemoryItem (POS: 跨 Agent
  共享记忆总线、并发连接池、背压守卫与方案否决账本的核心类型定义。)

[OUTPUT]
- ReinforcedDecayScorer: 记忆命中强化与时间半衰期衰减自学习评分器。

[POS]
命中频次正向强化与时间半衰期衰减联合打分器，实现常用常新、长期未用平滑遗忘。
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.shared_bus.types import (
    ReinforcedDecayConfig,
    ScoredMemoryItem,
)


class ReinforcedDecayScorer:
    """记忆命中强化与时间半衰期衰减自学习评分器。"""

    def __init__(self, config: ReinforcedDecayConfig | None = None) -> None:
        self.config = config or ReinforcedDecayConfig()

    def compute_score(
        self,
        base_weight: float,
        hit_count: int,
        last_accessed_at: str | None = None,
        now: datetime | None = None,
    ) -> tuple[float, float, float]:
        """计算记忆条目的 (复合得分, 衰减因子, 强化因子)。

        公式:
          强化因子 R = 1 + alpha * ln(1 + max(0, hit_count))
          衰减因子 D = 2 ** (- (delta_days / half_life_days))
          复合得分 S = max(min_floor, base_weight * R * D)
        """
        # 1. 命中强化因子
        safe_hits = max(0, hit_count)
        reinforcement_factor = 1.0 + self.config.hit_reinforcement_alpha * math.log(
            1.0 + safe_hits
        )

        # 2. 时间衰减因子
        current_time = now or datetime.now(UTC)
        if last_accessed_at:
            try:
                # 兼容带 Z 或偏移的时间戳
                cleaned = last_accessed_at.replace("Z", "+00:00")
                access_dt = datetime.fromisoformat(cleaned)
                if access_dt.tzinfo is None:
                    access_dt = access_dt.replace(tzinfo=UTC)
                delta_seconds = max(0.0, (current_time - access_dt).total_seconds())
                delta_days = delta_seconds / 86400.0
            except Exception:
                delta_days = 0.0
        else:
            delta_days = 0.0

        if self.config.half_life_days > 0:
            decay_factor = math.pow(2.0, -(delta_days / self.config.half_life_days))
        else:
            decay_factor = 1.0

        # 3. 复合加权得分
        raw_score = base_weight * reinforcement_factor * decay_factor
        composite_score = max(self.config.min_score_floor, raw_score)

        return composite_score, decay_factor, reinforcement_factor

    def score_item(
        self,
        memory_id: str,
        content: str,
        base_weight: float,
        hit_count: int,
        last_accessed_at: str | None = None,
        now: datetime | None = None,
    ) -> ScoredMemoryItem:
        """对单条记忆计算评分并返回打分模型。"""
        current_time = now or datetime.now(UTC)
        access_str = last_accessed_at or current_time.isoformat()
        composite_score, decay, reinf = self.compute_score(
            base_weight=base_weight,
            hit_count=hit_count,
            last_accessed_at=access_str,
            now=current_time,
        )
        return ScoredMemoryItem(
            memory_id=memory_id,
            content=content,
            base_weight=base_weight,
            hit_count=hit_count,
            last_accessed_at=access_str,
            composite_score=round(composite_score, 4),
            decay_factor=round(decay, 4),
            reinforcement_factor=round(reinf, 4),
        )

    def rank_items(
        self, items: list[ScoredMemoryItem], reverse: bool = True
    ) -> list[ScoredMemoryItem]:
        """按复合得分对记忆条目进行排序。"""
        return sorted(items, key=lambda x: x.composite_score, reverse=reverse)
