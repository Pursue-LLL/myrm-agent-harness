"""
[INPUT]
- myrm_agent_harness.agent.sub_agents.ralph_loop.types
- myrm_agent_harness.agent.sub_agents.ralph_loop.protocol
- myrm_agent_harness.agent.sub_agents.ralph_loop.runner

[OUTPUT]
- RalphHandoffStatus
- RalphHandoffReport
- RalphRoundRecord
- RalphLoopConfig
- RalphLoopSession
- sanitize_handoff_report
- evaluate_blocked_guardrail
- compose_fresh_agent_directive
- RalphFreshAgentLoopCoordinator
- get_ralph_loop_coordinator

[POS]
Harness 框架层 Ralph 式 Fresh-Agent 多轮循环模块门面（Topic 12 · 第 15 项）。
提供每轮启动无历史子 Agent、流转 5 字段交接与满 3 轮阻断防御。
"""

from myrm_agent_harness.agent.sub_agents.ralph_loop.protocol import (
    compose_fresh_agent_directive,
    evaluate_blocked_guardrail,
    sanitize_handoff_report,
)
from myrm_agent_harness.agent.sub_agents.ralph_loop.runner import (
    RalphFreshAgentLoopCoordinator,
    get_ralph_loop_coordinator,
)
from myrm_agent_harness.agent.sub_agents.ralph_loop.types import (
    DEFAULT_MAX_HANDOFF_CHARS,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MIN_ROUNDS_BEFORE_BLOCKED,
    RalphHandoffReport,
    RalphHandoffStatus,
    RalphLoopConfig,
    RalphLoopSession,
    RalphRoundRecord,
)

__all__ = [
    "DEFAULT_MAX_HANDOFF_CHARS",
    "DEFAULT_MAX_ROUNDS",
    "DEFAULT_MIN_ROUNDS_BEFORE_BLOCKED",
    "RalphHandoffReport",
    "RalphHandoffStatus",
    "RalphLoopConfig",
    "RalphLoopSession",
    "RalphRoundRecord",
    "RalphFreshAgentLoopCoordinator",
    "compose_fresh_agent_directive",
    "evaluate_blocked_guardrail",
    "get_ralph_loop_coordinator",
    "sanitize_handoff_report",
]
