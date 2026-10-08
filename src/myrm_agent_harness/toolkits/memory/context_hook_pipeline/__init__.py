"""Pluggable Context Hook Pipeline and Dual-Layer Memory Injection package.

Topic 01 Item 138: PluggableContextHookPipelineAndMemoryInjectionSuite.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.context_hook_pipeline.dual_layer_weaver import (
    DualLayerMemoryWeaver,
    WeavingOutcome,
)
from myrm_agent_harness.toolkits.memory.context_hook_pipeline.facade import (
    ContextHookPipelineSuite,
)
from myrm_agent_harness.toolkits.memory.context_hook_pipeline.models import (
    ContextEnvelope,
    ContextHookStage,
    DualLayerMemoryPayload,
    HookExecutionPriority,
    HookExecutionReport,
    MemoryFragment,
    MemoryLayerKind,
)
from myrm_agent_harness.toolkits.memory.context_hook_pipeline.pipeline import (
    HookCallable,
    PluggableContextHookPipeline,
    RegisteredHook,
)

__all__ = [
    "ContextEnvelope",
    "ContextHookPipelineSuite",
    "ContextHookStage",
    "DualLayerMemoryPayload",
    "DualLayerMemoryWeaver",
    "HookCallable",
    "HookExecutionPriority",
    "HookExecutionReport",
    "MemoryFragment",
    "MemoryLayerKind",
    "PluggableContextHookPipeline",
    "RegisteredHook",
    "WeavingOutcome",
]
