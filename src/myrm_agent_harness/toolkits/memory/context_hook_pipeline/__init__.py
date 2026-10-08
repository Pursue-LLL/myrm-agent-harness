"""Pluggable Context Hook Pipeline and Dual-Layer Memory Injection package.

[INPUT]
- memory.context_hook_pipeline.facade::ContextHookPipelineSuite (POS: Single entry point of the context hook pipeline package)
- memory.context_hook_pipeline.pipeline::{PluggableContextHookPipeline, RegisteredHook, HookCallable} (POS: Synchronous hook chain of the context hook pipeline package)
- memory.context_hook_pipeline.dual_layer_weaver::{DualLayerMemoryWeaver, WeavingOutcome} (POS: Dual-layer memory weaver of the context hook pipeline package)
- memory.context_hook_pipeline.models::{ContextEnvelope, ContextHookStage, DualLayerMemoryPayload, HookExecutionPriority, HookExecutionReport, MemoryFragment, MemoryLayerKind} (POS: Data contracts of the context hook pipeline package)

[OUTPUT]
- ContextHookPipelineSuite, PluggableContextHookPipeline, DualLayerMemoryWeaver: facade, hook chain and memory weaver
- ContextEnvelope, ContextHookStage, DualLayerMemoryPayload, HookExecutionPriority, HookExecutionReport, MemoryFragment, MemoryLayerKind, RegisteredHook, HookCallable, WeavingOutcome: data models and hook types of the pipeline

[POS]
Public entry of the context hook pipeline package. Re-exported by the memory toolkit and consumed by the server's context hooks provider.
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
