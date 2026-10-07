"""辩证推理深度用户表征引擎，从对话深层推断潜意识偏好与抗拒点，生成前缀缓存友好的认知切片。

[INPUT]
- toolkits.memory.dialectic.cadence_governor::DialecticCadenceGovernor (POS:
  自适应会话步调动态节流控制器与冷热状态机，严厉抑制冗余推理与 Token 消耗。)
- toolkits.memory.dialectic.types::DialecticCadenceConfig, DialecticEphemeralMind, DialecticReasoningResult,
  SessionHeatState (POS: 辩证推理深度用户表征与自适应会话步调动态节流核心类型。)

[OUTPUT]
- DialecticReasoningEngine: 辩证推理提炼引擎，纯本地开箱即用并支持会话步调节流。

[POS]
辩证推理深度用户表征引擎，从对话深层推断潜意识偏好与抗拒点，生成前缀缓存友好的认知切片。
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.dialectic.cadence_governor import (
    DialecticCadenceGovernor,
)
from myrm_agent_harness.toolkits.memory.dialectic.types import (
    DialecticCadenceConfig,
    DialecticEphemeralMind,
    DialecticReasoningResult,
    SessionHeatState,
)


class DialecticReasoningEngine:
    """辩证推理提炼引擎，纯本地开箱即用并支持会话步调节流。"""

    def __init__(
        self,
        config: DialecticCadenceConfig | None = None,
        governor: DialecticCadenceGovernor | None = None,
    ) -> None:
        self.config = config or DialecticCadenceConfig()
        self.governor = governor or DialecticCadenceGovernor(config=self.config)
        self._latest_mind: dict[str, DialecticEphemeralMind] = {}

    def get_latest_mind(self, conversation_id: str) -> DialecticEphemeralMind | None:
        """获取指定会话最新的即时心智认知状态。"""
        return self._latest_mind.get(conversation_id)

    @staticmethod
    def _extract_resistance_points(text: str) -> list[str]:
        """启发式提取用户的明确抗拒点与否定诉求。"""
        patterns = [
            r"(?:不要|严禁|杜绝|避免|拒绝|别用|讨厌|不要引入|不可)([^，。！？\n]{3,30})",
            r"(?:don't|never|avoid|no need for|do not use)\s+([^,.\n]{3,40})",
        ]
        resistances: list[str] = []
        for p in patterns:
            matches = re.findall(p, text, flags=re.IGNORECASE)
            for m in matches:
                cleaned = m.strip()
                if cleaned and cleaned not in resistances:
                    resistances.append(cleaned)
        return resistances[:3]

    @staticmethod
    def _extract_implicit_goals(text: str) -> list[str]:
        """启发式提取用户的潜意识深层期望与隐式目标。"""
        patterns = [
            r"(?:追求|希望|核心目标是|优先考虑|务必保证|重点在于)([^，。！？\n]{3,30})",
            r"(?:aiming for|prioritize|must ensure|key goal is)\s+([^,.\n]{3,40})",
        ]
        goals: list[str] = []
        for p in patterns:
            matches = re.findall(p, text, flags=re.IGNORECASE)
            for m in matches:
                cleaned = m.strip()
                if cleaned and cleaned not in goals:
                    goals.append(cleaned)
        return goals[:3]

    def render_volatile_prompt_slice(self, mind: DialecticEphemeralMind) -> str:
        """渲染紧凑高效的 Volatile 认知切片 (严格控制在字数上限内)。"""
        lines: list[str] = [
            "<!-- [USER DIALECTIC MIND] 即时心智状态与瞬间关切 -->",
            f"焦点: {mind.immediate_focus}",
        ]
        if mind.resistance_points:
            lines.append(f"抗拒点: {', '.join(mind.resistance_points)}")
        if mind.implicit_goals:
            lines.append(f"隐式诉求: {', '.join(mind.implicit_goals)}")

        raw_slice = "\n".join(lines)
        if len(raw_slice) > self.config.max_ephemeral_chars:
            return raw_slice[: self.config.max_ephemeral_chars - 3] + "..."
        return raw_slice

    def process_turn(
        self,
        conversation_id: str,
        user_prompt: str,
        assistant_response: str = "",
        turn_index: int | None = None,
    ) -> DialecticReasoningResult:
        """处理一轮交互，结合步调节流状态机执行辩证推理提炼。"""
        current_turn = self.governor.record_turn(conversation_id, turn_index)
        heat_state = self.governor.get_heat_state(conversation_id)

        # 1. 检查是否被步调节流拦截
        should_extract = self.governor.should_extract_ephemeral(conversation_id)
        if not should_extract:
            cached_mind = self._latest_mind.get(conversation_id)
            prompt_slice = (
                self.render_volatile_prompt_slice(cached_mind)
                if cached_mind
                else ""
            )
            return DialecticReasoningResult(
                conversation_id=conversation_id,
                turn_index=current_turn,
                is_throttled=True,
                heat_state=heat_state,
                base_profile_updated=False,
                ephemeral_mind_updated=False,
                ephemeral_mind=cached_mind,
                prompt_volatile_slice=prompt_slice,
                reasoning_summary=f"Turn #{current_turn} throttled by cadence governor (cadence={self.config.ephemeral_cadence_turns})",
            )

        # 2. 执行辩证推理提炼
        resistances = self._extract_resistance_points(user_prompt)
        goals = self._extract_implicit_goals(user_prompt)

        # 生成焦点总结
        cleaned_prompt = user_prompt.strip().replace("\n", " ")
        if len(cleaned_prompt) > 80:
            immediate_focus = cleaned_prompt[:77] + "..."
        else:
            immediate_focus = cleaned_prompt or "常规任务推进"

        if heat_state == SessionHeatState.COLD_BOOT:
            immediate_focus = f"[冷启动画像探测] {immediate_focus}"

        new_mind = DialecticEphemeralMind(
            conversation_id=conversation_id,
            immediate_focus=immediate_focus,
            resistance_points=resistances,
            implicit_goals=goals,
            confidence=0.9 if heat_state == SessionHeatState.HOT_ACTIVE else 0.75,
            turn_index=current_turn,
        )
        self._latest_mind[conversation_id] = new_mind
        self.governor.mark_ephemeral_extracted(conversation_id)

        # 检查基础静态画像刷新
        base_updated = False
        if self.governor.should_refresh_base_profile(conversation_id):
            self.governor.mark_base_profile_refreshed(conversation_id)
            base_updated = True

        prompt_slice = self.render_volatile_prompt_slice(new_mind)
        summary = (
            f"Turn #{current_turn} dialectic extraction complete. Focus: {immediate_focus}; "
            f"Resistances: {len(resistances)}; Goals: {len(goals)}; Base updated: {base_updated}"
        )

        return DialecticReasoningResult(
            conversation_id=conversation_id,
            turn_index=current_turn,
            is_throttled=False,
            heat_state=heat_state,
            base_profile_updated=base_updated,
            ephemeral_mind_updated=True,
            ephemeral_mind=new_mind,
            prompt_volatile_slice=prompt_slice,
            reasoning_summary=summary,
        )
