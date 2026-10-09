# [INPUT]: Modules in prompt_cache_roll_forward
# [OUTPUT]: Public symbols for PromptCacheDynamicRollForwardAndHeadless3DSandboxSuite
# [POS]: myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.__init__
"""Prompt Cache Dynamic Roll-Forward and Headless 3D Sandbox Suite (Item 330).

Provides dynamic prompt cache breakpoint roll-forward across tool execution rounds,
continuous cache miss spike anomaly circuit-breaking, pure-CPU headless 3D CAD modeling,
and long-horizon task version telemetry.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.cache_miss_anomaly_guard import (
    CacheMissAnomalyGuard,
)
from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.dynamic_roll_forward_engine import (
    DynamicRollForwardEngine,
)
from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.headless_3d_sandbox_adapter import (
    Headless3DSandboxAdapter,
    validate_3d_script_safety,
)
from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.long_task_telemetry import (
    LongTaskTelemetryTracker,
)
from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.roll_forward_suite import (
    PromptCacheDynamicRollForwardAndHeadless3DSandboxSuite,
)
from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.roll_forward_types import (
    COLD_MISS_TOKEN_THRESHOLD,
    MAX_CACHE_BREAKPOINTS,
    MAX_CONSECUTIVE_COLD_MISSES,
    AnomalyGuardStatus,
    CacheBreakpointInfo,
    CacheMissAnomalyReport,
    DynamicRollForwardResult,
    Headless3DEngineType,
    Headless3DExecutionResult,
    Headless3DScriptRequest,
    LongTaskIterationSnapshot,
    RollForwardStrategy,
)

__all__ = [
    "AnomalyGuardStatus",
    "COLD_MISS_TOKEN_THRESHOLD",
    "CacheBreakpointInfo",
    "CacheMissAnomalyGuard",
    "CacheMissAnomalyReport",
    "DynamicRollForwardEngine",
    "DynamicRollForwardResult",
    "Headless3DEngineType",
    "Headless3DExecutionResult",
    "Headless3DSandboxAdapter",
    "Headless3DScriptRequest",
    "LongTaskIterationSnapshot",
    "LongTaskTelemetryTracker",
    "MAX_CACHE_BREAKPOINTS",
    "MAX_CONSECUTIVE_COLD_MISSES",
    "PromptCacheDynamicRollForwardAndHeadless3DSandboxSuite",
    "RollForwardStrategy",
    "validate_3d_script_safety",
]
