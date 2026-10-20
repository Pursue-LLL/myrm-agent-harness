"""
[INPUT]
- pydantic (BaseModel, Field)
- typing (Literal)
- time (time)

[OUTPUT]
- RalphHandoffStatus: 轮次交接状态枚举字面量
- RalphHandoffReport: 结构化五字段交接报告实体
- RalphRoundRecord: 单轮次执行历史快照记录
- RalphLoopSession: Ralph 多轮循环会话主状态实体
- RalphLoopConfig: Ralph 循环运行策略配置

[POS]
Harness 框架层 Ralph 式 Fresh-Agent 多轮循环数据契约（Topic 12 · 第 15 项）。
严格定义五字段交接契约、容量硬顶约束与状态模型，杜绝任何 Any 类型。
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

RalphHandoffStatus = Literal["in_progress", "blocked", "completed"]

DEFAULT_MAX_HANDOFF_CHARS: int = 1500
DEFAULT_MIN_ROUNDS_BEFORE_BLOCKED: int = 3
DEFAULT_MAX_ROUNDS: int = 10


class RalphHandoffReport(BaseModel):
    """
    Ralph 模式五字段结构化交接报告。
    跨轮次仅传递此 5 字段极简信息，结合工作区文件实现满血无历史推理。
    """

    status: RalphHandoffStatus = Field(
        ...,
        description="本轮执行结果状态：in_progress (继续) | blocked (阻塞) | completed (已达成)",
    )
    summary: str = Field(
        ...,
        min_length=1,
        description="本轮工作极简执行摘要",
    )
    evidence: str = Field(
        ...,
        description="验收凭据：修改的代码文件路径、测试报告或产物链接",
    )
    next_steps: str = Field(
        ...,
        description="给下一轮全新 Fresh Agent 的具体工作指示",
    )
    blocker: str = Field(
        default="",
        description="若状态为 blocked 时的具体阻塞成因，否则为空字符串",
    )

    def total_chars(self) -> int:
        """计算交接报告 5 个字段的总字符开销。"""
        return (
            len(self.status)
            + len(self.summary)
            + len(self.evidence)
            + len(self.next_steps)
            + len(self.blocker)
        )


class RalphRoundRecord(BaseModel):
    """单个 Fresh Agent 轮次的记录凭证。"""

    round_index: int = Field(..., ge=1, description="当前轮次序号 (从 1 起始)")
    child_session_id: str = Field(..., description="本轮 Fresh 子代理的独立会话 ID")
    handoff: RalphHandoffReport = Field(..., description="本轮产生的五字段交接报告")
    created_at: float = Field(default_factory=time.time, description="轮次完成时间戳")
    duration_seconds: float = Field(default=0.0, description="本轮耗时 (秒)")
    tokens_consumed: int = Field(default=0, description="本轮消耗的 Token 数量")
    was_blocked_downgraded: bool = Field(
        default=False,
        description="是否因未满足至少尝试 3 轮规则而触发 blocked -> in_progress 防御降级",
    )


class RalphLoopConfig(BaseModel):
    """Ralph 多轮循环运行规则配置。"""

    max_rounds: int = Field(default=DEFAULT_MAX_ROUNDS, ge=1, le=50, description="最大允许执行轮次")
    min_rounds_before_blocked: int = Field(
        default=DEFAULT_MIN_ROUNDS_BEFORE_BLOCKED,
        ge=1,
        description="允许声明 blocked 的最小尝试轮次门槛",
    )
    max_handoff_chars: int = Field(
        default=DEFAULT_MAX_HANDOFF_CHARS,
        ge=200,
        le=5000,
        description="五字段交接报告总字符硬顶",
    )
    human_goal_locked: bool = Field(default=True, description="人类根目标是否严格锁定不可篡改")


class RalphLoopSession(BaseModel):
    """Ralph 多轮循环会话主模型。"""

    session_id: str = Field(..., description="Ralph 循环主会话 ID")
    human_goal: str = Field(..., min_length=1, description="人类设定的根本任务目标（子 Agent 严禁篡改）")
    workspace_root: str = Field(..., description="跨轮共享工作区物理绝对路径")
    current_round: int = Field(default=1, ge=1, description="当前进行或下一轮序号")
    status: RalphHandoffStatus = Field(default="in_progress", description="整体工作流聚合状态")
    config: RalphLoopConfig = Field(default_factory=RalphLoopConfig, description="循环控制策略")
    rounds: list[RalphRoundRecord] = Field(default_factory=list, description="历次轮次执行记录列表")
