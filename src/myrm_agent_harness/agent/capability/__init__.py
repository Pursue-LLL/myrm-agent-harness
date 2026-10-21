"""智能体能力纪元与动态上下文 JIT 重构模块。

提供 CapabilityEpochHasher 与 TurnBoundaryEpochValidator，
实现内容缓存 O(1) 毫秒级比对与配置修改即时热生效。

[INPUT]
- __future__

[OUTPUT]
- (模块级副作用与注册)

[POS]
智能体能力纪元与动态上下文 JIT 重构模块。
"""

from __future__ import annotations

from myrm_agent_harness.agent.capability.epoch_hasher import (
    CanonicalCapabilityManifest,
    CapabilityEpochHasher,
)
from myrm_agent_harness.agent.capability.session_invalidator import (
    CompiledAgentContext,
    SessionCapabilityState,
    TurnBoundaryEpochValidator,
    ValidationResult,
)

__all__ = [
    "CanonicalCapabilityManifest",
    "CapabilityEpochHasher",
    "CompiledAgentContext",
    "SessionCapabilityState",
    "TurnBoundaryEpochValidator",
    "ValidationResult",
]
