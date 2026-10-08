"""Pluggable Context Hook Pipeline and Dual-Layer Memory Injection package.

[INPUT]
- memory.context_hook_pipeline.facade::ContextHookPipelineSuite (POS: single entry point for lifecycle hooks and memory weaving)
- memory.context_hook_pipeline.pipeline::{PluggableContextHookPipeline, RegisteredHook, HookCallable} (POS: synchronous hook chain)
- memory.context_hook_pipeline.dual_layer_weaver::{DualLayerMemoryWeaver, WeavingOutcome} (POS: budgeted private-first memory weaver)
- memory.context_hook_pipeline.models::{ContextEnvelope, ContextHookStage, DualLayerMemoryPayload, HookExecutionPriority, HookExecutionReport, MemoryFragment, MemoryLayerKind} (POS: data contracts of the context hook pipeline package)

[OUTPUT]
- the facade, hook chain, memory weaver and data model names re-exported through __all__

[POS]
Public entry of the context hook pipeline package, re-exported by the memory toolkit and consumed by the server's context hooks provider.
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
