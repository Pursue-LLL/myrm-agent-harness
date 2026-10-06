# [POS] myrm_agent_harness/toolkits/memory/dialectic/__init__.py
# [INPUT] types, cadence_governor, dialectic_engine
# [OUTPUT] 统一导出辩证推理深度用户表征与自适应步调节流套件核心符号

"""辩证推理深度用户表征与自适应会话步调动态节流套件。"""

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
