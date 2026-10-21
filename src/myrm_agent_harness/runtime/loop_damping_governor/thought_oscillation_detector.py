"""思考振荡与乒乓编辑模式探针模块.

本模块通过滑窗追踪最近几轮的工具动作与代码修改签名，
精准识别乒乓横跳（A -> B -> A）、零增量空转与死循环工具链，并自动生成人机裁定卡。

[INPUT]
- __future__
- logging
- collections

[OUTPUT]
- logger
- ThoughtOscillationDetector

[POS]
思考振荡与乒乓编辑模式探针模块.
"""

from __future__ import annotations

import logging
from collections import deque

from myrm_agent_harness.runtime.loop_damping_governor.oscillation_guard_types import (
    ActionFingerprint,
    HumanTiebreakerCard,
    OscillationPatternType,
    OscillationVerdict,
)

logger = logging.getLogger(__name__)


class ThoughtOscillationDetector:
    """思考与行为振荡探针."""

    def __init__(self, window_size: int = 4) -> None:
        self.window_size: int = window_size
        self._history: deque[ActionFingerprint] = deque(maxlen=window_size)
        # 记录每个 target 的历史状态签名列表: target -> list[signature]
        self._target_signatures: dict[str, list[tuple[str, str]]] = {}  # (sig, summary)

    def record_action(
        self,
        step_index: int,
        target_identifier: str,
        state_signature: str,
        summary: str = "",
    ) -> None:
        """记录一轮执行动作或文件改动的指纹."""
        fp = ActionFingerprint(
            step_index=step_index,
            target_identifier=target_identifier,
            state_signature=state_signature,
            summary=summary,
        )
        self._history.append(fp)

        if target_identifier not in self._target_signatures:
            self._target_signatures[target_identifier] = []
        self._target_signatures[target_identifier].append((state_signature, summary))

    def detect_oscillation(self) -> OscillationVerdict:
        """检测当前滑窗内是否存在思考或行为振荡模式."""
        # 1. 优先检测乒乓编辑模式（A -> B -> A）
        ping_pong_verdict = self._check_ping_pong_edit()
        if ping_pong_verdict.is_oscillating:
            return ping_pong_verdict

        # 2. 检测工具链循环死循环（A -> B -> A -> B）
        cyclic_verdict = self._check_cyclic_tool_chain()
        if cyclic_verdict.is_oscillating:
            return cyclic_verdict

        # 3. 检测连续无进展零语义增量（A -> A -> A）
        zero_progress_verdict = self._check_zero_progress()
        if zero_progress_verdict.is_oscillating:
            return zero_progress_verdict

        return OscillationVerdict(is_oscillating=False)

    def _check_ping_pong_edit(self) -> OscillationVerdict:
        """检测单个目标的乒乓往返横跳特征."""
        for target, history in self._target_signatures.items():
            if len(history) >= 3:
                # 检查最近 3 次修改签名
                sig1, sum1 = history[-3]
                sig2, sum2 = history[-2]
                sig3, sum3 = history[-1]

                # 若状态从 sig1 变为 sig2，随后又变回 sig1（且 sig1 != sig2）
                if sig1 == sig3 and sig1 != sig2:
                    card = HumanTiebreakerCard(
                        dispute_summary=f"检测到在目标 '{target}' 的两个对立方案之间反复倒腾覆盖",
                        affected_target=target,
                        option_a_summary=sum1 or f"方案 A (特征: {sig1[:8]})",
                        option_b_summary=sum2 or f"方案 B (特征: {sig2[:8]})",
                        recommended_option=f"方案 A (基于最近一次恢复状态: {sum3 or sig3[:8]})",
                    )
                    msg = (
                        f"Ping-pong edit oscillation detected on target '{target}': "
                        f"State cycled {sig1[:8]} -> {sig2[:8]} -> {sig3[:8]}"
                    )
                    logger.warning(msg)
                    return OscillationVerdict(
                        is_oscillating=True,
                        pattern=OscillationPatternType.PING_PONG_EDIT,
                        affected_targets=[target],
                        explanation=msg,
                        tiebreaker_card=card,
                    )
        return OscillationVerdict(is_oscillating=False)

    def _check_cyclic_tool_chain(self) -> OscillationVerdict:
        """检测工具调用链的二元闭环循环（T1 -> T2 -> T1 -> T2）."""
        if len(self._history) == 4:
            t0, t1, t2, t3 = (
                self._history[0].target_identifier,
                self._history[1].target_identifier,
                self._history[2].target_identifier,
                self._history[3].target_identifier,
            )
            if t0 == t2 and t1 == t3 and t0 != t1:
                msg = f"Cyclic tool chain detected: {t0} -> {t1} -> {t2} -> {t3}"
                logger.warning(msg)
                return OscillationVerdict(
                    is_oscillating=True,
                    pattern=OscillationPatternType.CYCLIC_TOOL_CHAIN,
                    affected_targets=[t0, t1],
                    explanation=msg,
                )
        return OscillationVerdict(is_oscillating=False)

    def _check_zero_progress(self) -> OscillationVerdict:
        """检测连续 3 轮同一目标且状态签名完全不变的空转停滞."""
        if len(self._history) >= 3:
            recent = list(self._history)[-3:]
            first_target = recent[0].target_identifier
            first_sig = recent[0].state_signature

            all_identical = all(
                h.target_identifier == first_target and h.state_signature == first_sig
                for h in recent
            )
            if all_identical:
                msg = (
                    f"Zero semantic progress detected across 3 steps on target "
                    f"'{first_target}' with unchanged signature '{first_sig[:8]}'"
                )
                logger.warning(msg)
                return OscillationVerdict(
                    is_oscillating=True,
                    pattern=OscillationPatternType.ZERO_SEMANTIC_PROGRESS,
                    affected_targets=[first_target],
                    explanation=msg,
                )
        return OscillationVerdict(is_oscillating=False)
