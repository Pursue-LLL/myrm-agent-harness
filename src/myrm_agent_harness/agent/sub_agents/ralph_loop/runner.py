"""
[INPUT]
- typing (dict, str, tuple, Optional)
- uuid (uuid4)
- time (time)
- myrm_agent_harness.agent.sub_agents.ralph_loop.types (RalphHandoffReport, RalphRoundRecord, RalphLoopConfig, RalphLoopSession, RalphHandoffStatus)
- myrm_agent_harness.agent.sub_agents.ralph_loop.protocol (sanitize_handoff_report, evaluate_blocked_guardrail, compose_fresh_agent_directive)

[OUTPUT]
- RalphFreshAgentLoopCoordinator: Ralph 多轮循环生命周期与交接流转协调器

[POS]
Harness 框架层 Ralph 式 Fresh-Agent 多轮循环执行协调器（Topic 12 · 第 15 项）。
单机无状态/内存会话注册表，实现 Fresh 子 Agent 启动指令装配、结构化五字段交接归档与阻断防御。
"""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.agent.sub_agents.ralph_loop.protocol import (
    compose_fresh_agent_directive,
    evaluate_blocked_guardrail,
    sanitize_handoff_report,
)
from myrm_agent_harness.agent.sub_agents.ralph_loop.types import (
    RalphHandoffReport,
    RalphLoopConfig,
    RalphLoopSession,
    RalphRoundRecord,
)


class RalphFreshAgentLoopCoordinator:
    """
    Ralph 模式 Fresh-Agent 多轮循环框架协调器。
    协调每轮启动无历史子 Agent、流转 5 字段交接、并在共享工作区物理文件上持续迭代。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, RalphLoopSession] = {}

    def create_session(
        self,
        human_goal: str,
        workspace_root: str,
        config: RalphLoopConfig | None = None,
        session_id: str | None = None,
    ) -> RalphLoopSession:
        """创建全新的 Ralph 多轮循环执行会话。"""
        actual_id = session_id or f"ralph-loop-{uuid.uuid4().hex[:8]}"
        actual_config = config or RalphLoopConfig()

        session = RalphLoopSession(
            session_id=actual_id,
            human_goal=human_goal,
            workspace_root=workspace_root,
            current_round=1,
            status="in_progress",
            config=actual_config,
            rounds=[],
        )
        self._sessions[actual_id] = session
        return session

    def get_session(self, session_id: str) -> RalphLoopSession | None:
        """获取指定 Ralph 循环会话状态。"""
        return self._sessions.get(session_id)

    def generate_next_round_directive(self, session_id: str) -> str:
        """
        装配下一轮 Fresh 子 Agent 的启动提示词。
        完全清零前序对话历史，仅由根目标 + 共享工作区 + 上轮 5 字段交接构成。
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Ralph session not found: {session_id}")

        prior_handoff: RalphHandoffReport | None = None
        if session.rounds:
            prior_handoff = session.rounds[-1].handoff

        return compose_fresh_agent_directive(
            human_goal=session.human_goal,
            workspace_root=session.workspace_root,
            round_index=session.current_round,
            max_rounds=session.config.max_rounds,
            prior_handoff=prior_handoff,
        )

    def record_round_completion(
        self,
        session_id: str,
        child_session_id: str,
        raw_handoff: RalphHandoffReport,
        duration_seconds: float = 0.0,
        tokens_consumed: int = 0,
    ) -> RalphRoundRecord:
        """
        归档单轮执行结果，执行五字段容量裁剪与 min-3-round 阻断门禁，推进轮次并流转状态。
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Ralph session not found: {session_id}")

        current_idx = session.current_round

        # 1. 容量硬顶清洗
        sanitized_report = sanitize_handoff_report(raw_handoff, session.config)

        # 2. 满三轮阻断防御门禁
        final_report, was_downgraded = evaluate_blocked_guardrail(
            sanitized_report,
            current_idx,
            session.config,
        )

        # 3. 构造轮次记录
        record = RalphRoundRecord(
            round_index=current_idx,
            child_session_id=child_session_id,
            handoff=final_report,
            created_at=time.time(),
            duration_seconds=max(0.0, duration_seconds),
            tokens_consumed=max(0, tokens_consumed),
            was_blocked_downgraded=was_downgraded,
        )
        session.rounds.append(record)

        # 4. 判定全局会话状态流转
        if final_report.status == "completed":
            session.status = "completed"
        elif final_report.status == "blocked":
            # 经过 evaluate_blocked_guardrail 仍为 blocked 说明已满 3 轮门槛
            session.status = "blocked"
        else:
            # 仍处于 in_progress
            if current_idx >= session.config.max_rounds:
                # 触达轮次上限，强制终止为 blocked
                session.status = "blocked"
            else:
                session.current_round += 1
                session.status = "in_progress"

        return record


# 框架全局单例
_GLOBAL_COORDINATOR: RalphFreshAgentLoopCoordinator | None = None


def get_ralph_loop_coordinator() -> RalphFreshAgentLoopCoordinator:
    """获取或初始化全局单机 Ralph 多轮循环协调器。"""
    global _GLOBAL_COORDINATOR
    if _GLOBAL_COORDINATOR is None:
        _GLOBAL_COORDINATOR = RalphFreshAgentLoopCoordinator()
    return _GLOBAL_COORDINATOR
