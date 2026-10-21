"""Public surface of the context guard subsystem.

[INPUT]
- agent.context_guard.spillover_engine::SpilloverEngine
  (POS: 透明溢出引擎层)
- agent.context_guard.sweeper::EphemeralTransientSweeper
  (POS: 过期溢出文件清理层)
- agent.context_guard.types::ContextGuardConfig, SpilloverPayload, SpilloverResult,
  estimate_token_pressure (POS: 上下文守卫数据模型与 token 压力估算层)

[OUTPUT]
- SpilloverEngine: atomic extraction of oversized payloads into referenced files
- EphemeralTransientSweeper: TTL cleanup for ephemeral spillover files
- ContextGuardConfig, SpilloverPayload, SpilloverResult, estimate_token_pressure

[POS]
Package entry point for context safety. Import from here rather than from the individual
modules so the internal layout stays free to change. Framework-level: keeps the agent run
alive by converting context bombs into file references instead of dropping them.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_guard.spillover_engine import SpilloverEngine
from myrm_agent_harness.agent.context_guard.sweeper import EphemeralTransientSweeper
from myrm_agent_harness.agent.context_guard.types import (
    ContextGuardConfig,
    SpilloverPayload,
    SpilloverResult,
    estimate_token_pressure,
)

__all__ = [
    "ContextGuardConfig",
    "EphemeralTransientSweeper",
    "SpilloverEngine",
    "SpilloverPayload",
    "SpilloverResult",
    "estimate_token_pressure",
]
