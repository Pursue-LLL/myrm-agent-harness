"""Heartbeat Evaluator for Skill Review Trigger.

[INPUT]
- myrm_agent_harness.agent.types::AgentRunStats (POS: Agent 运行统计)

[OUTPUT]
- HeartbeatEvaluator: 评估是否触发技能复盘的纯逻辑类

[POS]
Heartbeat evaluator. Scores conversation health based on expression_volume and task_complexity metrics.

"""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


@dataclass
class HeartbeatConfig:
    """心跳阈值配置"""

    # 任务复杂度阈值（工具调用次数）
    min_tool_calls: int = 2
    # 用户表达量阈值（用户输入的总字符数或 Token 数近似）
    min_expression_length: int = 50
    # 最大允许复盘的工具调用深度（防爆炸）
    max_tool_calls: int = 50


class HeartbeatEvaluator:
    """评估会话是否满足技能复盘的“心跳”阈值。"""

    def __init__(self, config: HeartbeatConfig | None = None) -> None:
        self.config = config or HeartbeatConfig()

    def should_trigger_review(self, tool_call_count: int, user_expression_length: int) -> bool:
        """基于表达量和复杂度判断是否触发复盘。

        Args:
            tool_call_count: 本次任务执行的工具调用总数（代表任务复杂度）。
            user_expression_length: 用户原始 Query 的字符长度（代表用户表达量）。

        Returns:
            bool: 是否触发复盘。
        """
        # 1. 过滤过度复杂的暴走任务（节省 Token）
        if tool_call_count > self.config.max_tool_calls:
            logger.info(
                "Heartbeat suppressed: task too complex (tool_calls=%d > %d)",
                tool_call_count,
                self.config.max_tool_calls,
            )
            return False

        # 2. 检查任务复杂度（必须有实质性的探索或执行动作）
        complexity_met = tool_call_count >= self.config.min_tool_calls

        # 3. 检查用户表达量（用户必须提出了具备一定信息量的问题，而非单纯的“你好”、“继续”）
        expression_met = user_expression_length >= self.config.min_expression_length

        # 综合判定：深度交互才学（或者虽然话少，但是工具调用极多，证明这是一个简短指令引发的极复杂任务）
        # 启发式规则：
        # - 正常深度交互：表达量达标 AND 复杂度达标
        # - 短指令复杂任务：表达量未达标，但复杂度极高（>=4）
        if expression_met and complexity_met:
            logger.info(
                "Heartbeat triggered (Deep Interaction): expression_length=%d, tool_calls=%d",
                user_expression_length,
                tool_call_count,
            )
            return True
        elif not expression_met and tool_call_count >= max(4, self.config.min_tool_calls + 2):
            logger.info(
                "Heartbeat triggered (Short command, high complexity): expression_length=%d, tool_calls=%d",
                user_expression_length,
                tool_call_count,
            )
            return True

        logger.debug(
            "Heartbeat NOT triggered: expression_length=%d (min=%d), tool_calls=%d (min=%d)",
            user_expression_length,
            self.config.min_expression_length,
            tool_call_count,
            self.config.min_tool_calls,
        )
        return False
