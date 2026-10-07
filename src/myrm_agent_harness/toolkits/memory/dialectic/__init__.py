"""辩证推理深度用户表征与自适应会话步调动态节流套件。

[INPUT]
- toolkits.memory.dialectic.cadence_governor::DialecticCadenceGovernor (POS:
  自适应会话步调动态节流控制器与冷热状态机，严厉抑制冗余推理与 Token 消耗。)
- toolkits.memory.dialectic.dialectic_engine::DialecticReasoningEngine (POS:
  辩证推理深度用户表征引擎，从对话深层推断潜意识偏好与抗拒点，生成前缀缓存友好的认知切片。)
- toolkits.memory.dialectic.types::DialecticCadenceConfig, DialecticEphemeralMind, DialecticReasoningResult,
  SessionHeatState, UserBaseProfile (POS: 辩证推理深度用户表征与自适应会话步调动态节流核心类型。)

[OUTPUT]
- Package facade re-exporting 7 public names: DialecticCadenceConfig, DialecticCadenceGovernor,
  DialecticEphemeralMind, DialecticReasoningEngine, DialecticReasoningResult, SessionHeatState,
  UserBaseProfile

[POS]
辩证推理深度用户表征与自适应会话步调动态节流套件。
"""

from myrm_agent_harness.toolkits.memory.dialectic.cadence_governor import (
    DialecticCadenceGovernor,
)
from myrm_agent_harness.toolkits.memory.dialectic.dialectic_engine import (
    DialecticReasoningEngine,
)
from myrm_agent_harness.toolkits.memory.dialectic.types import (
    DialecticCadenceConfig,
    DialecticEphemeralMind,
    DialecticReasoningResult,
    SessionHeatState,
    UserBaseProfile,
)

__all__ = [
    "DialecticCadenceConfig",
    "DialecticCadenceGovernor",
    "DialecticEphemeralMind",
    "DialecticReasoningEngine",
    "DialecticReasoningResult",
    "SessionHeatState",
    "UserBaseProfile",
]
