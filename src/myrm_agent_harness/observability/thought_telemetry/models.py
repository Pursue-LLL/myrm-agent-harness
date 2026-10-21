"""[INPUT]
- dataclasses.dataclass, enum.StrEnum, typing (Standard library types)

[OUTPUT]
- RunawayReason: 思维链失控死循环原因枚举
- ThoughtTelemetrySnapshot: 思维流实时遥测指标快照
- ThoughtStepMarker: 思维推进步骤标记

[POS]
myrm_agent_harness.observability.thought_telemetry.models — 思考链流式遥测与失控守护数据模型。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class RunawayReason(StrEnum):
    """思维链失控或死循环原因。"""

    NONE = "none"
    EXCESSIVE_LENGTH = "excessive_length"  # 思考链超过安全预算上限
    NGRAM_REPETITION_LOOP = "ngram_repetition_loop"  # 检测到 N-gram 严重循环复读
    HIGH_DIVERGENCE = "high_divergence"  # 思维发散度过高且无收敛迹象


@dataclass(frozen=True, slots=True)
class ThoughtStepMarker:
    """思维演进中的单个反思/推演步骤。"""

    step_index: int
    title: str
    offset_chars: int
    detected_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class ThoughtTelemetrySnapshot:
    """思维流实时指标快照。"""

    elapsed_ms: float
    token_count: int
    step_count: int
    divergence_score: float  # 0.0 ~ 1.0
    repetition_ratio: float  # 0.0 ~ 1.0 (N-gram 重复率)
    is_runaway_detected: bool
    runaway_reason: RunawayReason
    soft_interrupt_hint: str | None = None
    captured_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "elapsed_ms": round(self.elapsed_ms, 1),
            "token_count": self.token_count,
            "step_count": self.step_count,
            "divergence_score": round(self.divergence_score, 3),
            "repetition_ratio": round(self.repetition_ratio, 3),
            "is_runaway_detected": self.is_runaway_detected,
            "runaway_reason": self.runaway_reason.value,
            "soft_interrupt_hint": self.soft_interrupt_hint,
            "captured_at": round(self.captured_at, 3),
        }
