# [POS] myrm_agent_harness/toolkits/memory/dialectic/cadence_governor.py
# [INPUT] DialecticCadenceConfig, SessionHeatState from .types
# [OUTPUT] DialecticCadenceGovernor (自适应会话步调动态节流控制器与冷热状态机)

"""自适应会话步调动态节流控制器与冷热状态机，严厉抑制冗余推理与 Token 消耗。"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.dialectic.types import (
    DialecticCadenceConfig,
    SessionHeatState,
)


class DialecticCadenceGovernor:
    """会话步调与冷热活跃度调度治理器。"""

    def __init__(self, config: DialecticCadenceConfig | None = None) -> None:
        self.config = config or DialecticCadenceConfig()
        self._session_turns: dict[str, int] = {}
        self._last_ephemeral_turn: dict[str, int] = {}
        self._last_base_turn: dict[str, int] = {}

    def record_turn(self, conversation_id: str, turn_index: int | None = None) -> int:
        """记录会话新的一轮交互，并返回更新后的轮次编号。"""
        if turn_index is not None:
            self._session_turns[conversation_id] = turn_index
            return turn_index
        current = self._session_turns.get(conversation_id, 0) + 1
        self._session_turns[conversation_id] = current
        return current

    def get_turn(self, conversation_id: str) -> int:
        """获取指定会话当前的轮次编号。"""
        return self._session_turns.get(conversation_id, 0)

    def get_heat_state(self, conversation_id: str) -> SessionHeatState:
        """计算当前会话冷热活跃状态。"""
        turn = self.get_turn(conversation_id)
        if turn <= self.config.cold_boot_threshold_turns:
            return SessionHeatState.COLD_BOOT
        if turn <= self.config.cold_boot_threshold_turns + 2:
            return SessionHeatState.WARM
        return SessionHeatState.HOT_ACTIVE

    def should_extract_ephemeral(self, conversation_id: str) -> bool:
        """判定当前轮次是否命中即时认知心智提炼步调。"""
        if not self.config.enable_throttling:
            return True

        turn = self.get_turn(conversation_id)
        if turn <= 0:
            return False

        last_turn = self._last_ephemeral_turn.get(conversation_id, 0)
        # 满足 cadence 间隔或者冷启动首轮
        return last_turn == 0 or (turn - last_turn) >= self.config.ephemeral_cadence_turns

    def mark_ephemeral_extracted(self, conversation_id: str) -> None:
        """标记本轮已完成即时心智提炼。"""
        self._last_ephemeral_turn[conversation_id] = self.get_turn(conversation_id)

    def should_refresh_base_profile(self, conversation_id: str) -> bool:
        """判定当前轮次是否命中长期基础画像低频评估步调。"""
        if not self.config.enable_throttling:
            return True

        turn = self.get_turn(conversation_id)
        if turn <= 0:
            return False

        last_turn = self._last_base_turn.get(conversation_id, 0)
        # 满足较长 cadence 步调
        return last_turn == 0 or (turn - last_turn) >= self.config.base_profile_cadence_turns

    def mark_base_profile_refreshed(self, conversation_id: str) -> None:
        """标记本轮已完成长期基础画像刷新。"""
        self._last_base_turn[conversation_id] = self.get_turn(conversation_id)

    def reset_session(self, conversation_id: str) -> None:
        """重置指定会话的步调追踪状态。"""
        self._session_turns.pop(conversation_id, None)
        self._last_ephemeral_turn.pop(conversation_id, None)
        self._last_base_turn.pop(conversation_id, None)
