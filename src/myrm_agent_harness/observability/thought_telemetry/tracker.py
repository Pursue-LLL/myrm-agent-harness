"""[INPUT]
- time, re, typing (Standard library algorithms & timing)
- myrm_agent_harness.observability.thought_telemetry.models::{
    RunawayReason,
    ThoughtStepMarker,
    ThoughtTelemetrySnapshot,
}
- myrm_agent_harness.observability.thought_telemetry.runaway_guard::{CoTRunawayGuard}

[OUTPUT]
- ThoughtTelemetryTracker: 思维流实时遥测追踪器与步骤分析引擎

[POS]
myrm_agent_harness.observability.thought_telemetry.tracker — 实时流式度量思考链字数、Token 数、耗时、推进步骤与发散度。
"""

from __future__ import annotations

import re
import time

from myrm_agent_harness.observability.thought_telemetry.models import (
    ThoughtStepMarker,
    ThoughtTelemetrySnapshot,
)
from myrm_agent_harness.observability.thought_telemetry.runaway_guard import CoTRunawayGuard

# 步骤特征识别正则：如 "Step 1", "1.", "首先", "接下来", "但是/Wait,", "重新审视" 等
_STEP_PATTERN = re.compile(
    r"(?:\n\s*(?:step\s*\d+|步骤\s*\d+|\d+\.)\s*|"
    r"(?:首先|其次|再次|最后|另外|但是|等等|等一下|重新考虑|仔细思考|wait,|let me reconsider|re-evaluating))",
    re.IGNORECASE,
)


class ThoughtTelemetryTracker:
    """思维流实时遥测追踪器。

    流式接收推理 Token / 文本块，提供：
    1. 思考耗时（ms）精准度量；
    2. 估算与精确 Token 统计；
    3. 自我纠偏步骤数（Step Count）自动识别；
    4. 发散度评分与死循环熔断报警。
    """

    def __init__(
        self,
        *,
        guard: CoTRunawayGuard | None = None,
        chars_per_token: float = 3.5,
    ) -> None:
        self.guard = guard or CoTRunawayGuard()
        self.chars_per_token = chars_per_token
        self._start_time = time.perf_counter()
        self._accumulated_text = ""
        self._step_markers: list[ThoughtStepMarker] = []
        self._last_matched_step_index = 0

    @property
    def accumulated_text(self) -> str:
        return self._accumulated_text

    @property
    def step_count(self) -> int:
        # 基础步骤至少为 1
        return max(1, len(self._step_markers))

    def estimate_tokens(self) -> int:
        """根据字符数快速估算 Token 数。"""
        if not self._accumulated_text:
            return 0
        return max(1, int(len(self._accumulated_text) / self.chars_per_token))

    def append_chunk(
        self,
        chunk: str,
        *,
        exact_tokens: int | None = None,
    ) -> ThoughtTelemetrySnapshot:
        """追加流式思维 chunk 并生成当前最新的遥测快照。"""
        if chunk:
            offset = len(self._accumulated_text)
            self._accumulated_text += chunk

            # 检测新步骤
            matches = list(_STEP_PATTERN.finditer(chunk))
            for m in matches:
                self._last_matched_step_index += 1
                self._step_markers.append(
                    ThoughtStepMarker(
                        step_index=self._last_matched_step_index,
                        title=m.group().strip(),
                        offset_chars=offset + m.start(),
                    )
                )

        now = time.perf_counter()
        elapsed_ms = (now - self._start_time) * 1000.0
        token_count = exact_tokens if exact_tokens is not None else self.estimate_tokens()

        # 检查死循环与失控熔断
        is_runaway, reason, rep_ratio, hint = self.guard.check_runaway(
            self._accumulated_text,
            token_count,
        )

        # 发散度评分：综合耗时、步骤数与失控特征
        # 步骤每增加一个或耗时增加，适度递增发散度，若触发死循环则打满
        base_divergence = min(0.85, (len(self._step_markers) * 0.12) + (token_count / 8000.0))
        divergence_score = 1.0 if is_runaway else base_divergence

        return ThoughtTelemetrySnapshot(
            elapsed_ms=elapsed_ms,
            token_count=token_count,
            step_count=self.step_count,
            divergence_score=divergence_score,
            repetition_ratio=rep_ratio,
            is_runaway_detected=is_runaway,
            runaway_reason=reason,
            soft_interrupt_hint=hint,
        )
