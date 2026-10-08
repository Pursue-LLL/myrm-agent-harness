"""Unified Facade for Pluggable Context Hook Pipeline and Dual-Layer Memory Weaving.

[INPUT]
- memory.context_hook_pipeline.pipeline::{PluggableContextHookPipeline, HookCallable, RegisteredHook} (POS: Synchronous hook chain of the context hook pipeline package)
- memory.context_hook_pipeline.dual_layer_weaver::{DualLayerMemoryWeaver, WeavingOutcome} (POS: Dual-layer memory weaver of the context hook pipeline package)
- memory.context_hook_pipeline.models::{ContextEnvelope, ContextHookStage, DualLayerMemoryPayload, HookExecutionReport} (POS: Data contracts of the context hook pipeline package)

[OUTPUT]
- ContextHookPipelineSuite: registers, unregisters and lists hooks, runs one stage, weaves memories into the envelope, counts hooks per stage and runs the standard lifecycle (start hooks, weaving, transform hooks, pre-LLM hooks), stopping early once a hook blocks the envelope

[POS]
Single entry point of the context hook pipeline package. Lets hosts register lifecycle hooks, run stages and weave memories through one object.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.context_hook_pipeline.dual_layer_weaver import (
    DualLayerMemoryWeaver,
    WeavingOutcome,
)
from myrm_agent_harness.toolkits.memory.context_hook_pipeline.models import (
    ContextEnvelope,
    ContextHookStage,
    DualLayerMemoryPayload,
    HookExecutionReport,
)
from myrm_agent_harness.toolkits.memory.context_hook_pipeline.pipeline import (
    HookCallable,
    PluggableContextHookPipeline,
    RegisteredHook,
)


class ContextHookPipelineSuite:
    """Coordinates lifecycle hook stages and dual-layer memory weaving."""

    def __init__(
        self,
        pipeline: PluggableContextHookPipeline | None = None,
        weaver: DualLayerMemoryWeaver | None = None,
    ) -> None:
        self._pipeline = pipeline or PluggableContextHookPipeline()
        self._weaver = weaver or DualLayerMemoryWeaver()

    # 1. Hook Registration
    def register_hook(
        self,
        hook_id: str,
        stage: ContextHookStage,
        handler: HookCallable,
        priority: int = 30,
        description: str = "",
    ) -> None:
        """Register an interceptor hook at a specific lifecycle stage."""
        self._pipeline.register_hook(
            hook_id=hook_id,
            stage=stage,
            handler=handler,
            priority=priority,
            description=description,
        )

    def unregister_hook(self, hook_id: str, stage: ContextHookStage) -> bool:
        """Unregister a hook by ID."""
        return self._pipeline.unregister_hook(hook_id=hook_id, stage=stage)

    def list_hooks(self, stage: ContextHookStage | None = None) -> list[RegisteredHook]:
        """List registered hooks."""
        return self._pipeline.list_hooks(stage=stage)

    # 2. Stage Execution
    def execute_stage(
        self,
        stage: ContextHookStage,
        envelope: ContextEnvelope,
    ) -> list[HookExecutionReport]:
        """Run all hooks for the specified stage."""
        return self._pipeline.execute_stage(stage=stage, envelope=envelope)

    # 3. Dual-Layer Memory Weaving
    def weave_memories(self, payload: DualLayerMemoryPayload) -> WeavingOutcome:
        """Weave private and shared memories without mutating an envelope."""
        return self._weaver.weave(payload)

    def weave_and_inject(
        self,
        payload: DualLayerMemoryPayload,
        envelope: ContextEnvelope,
    ) -> WeavingOutcome:
        """Weave memories and inject the formatted block into the context envelope."""
        outcome = self._weaver.weave(payload)
        if outcome.woven_block:
            envelope.injected_memories.append(outcome.woven_block)
        return outcome

    # 4. End-to-End Context Pipeline Execution
    def execute_full_lifecycle(
        self,
        envelope: ContextEnvelope,
        memory_payload: DualLayerMemoryPayload | None = None,
    ) -> dict[str, list[HookExecutionReport]]:
        """Run standard pipeline: BEFORE_AGENT_START -> Weave -> CONTEXT_TRANSFORM -> BEFORE_LLM_REQUEST."""
        all_reports: dict[str, list[HookExecutionReport]] = {}

        # Stage 1: Before Agent Start
        r1 = self.execute_stage(ContextHookStage.BEFORE_AGENT_START, envelope)
        all_reports[ContextHookStage.BEFORE_AGENT_START.value] = r1
        if envelope.is_blocked:
            return all_reports

        # Stage 2: Memory Weaving
        if memory_payload is not None:
            self.weave_and_inject(memory_payload, envelope)

        # Stage 3: Context Transform
        r2 = self.execute_stage(ContextHookStage.CONTEXT_TRANSFORM, envelope)
        all_reports[ContextHookStage.CONTEXT_TRANSFORM.value] = r2
        if envelope.is_blocked:
            return all_reports

        # Stage 4: Before LLM Request (Sanitization)
        r3 = self.execute_stage(ContextHookStage.BEFORE_LLM_REQUEST, envelope)
        all_reports[ContextHookStage.BEFORE_LLM_REQUEST.value] = r3

        return all_reports

    # 5. Telemetry & Stats
    def get_stats(self) -> dict[str, int]:
        """Collect registered hooks statistics."""
        hooks = self.list_hooks()
        stats: dict[str, int] = {
            "total_hooks": len(hooks),
            "before_agent_start": len(self._pipeline.list_hooks(ContextHookStage.BEFORE_AGENT_START)),
            "context_transform": len(self._pipeline.list_hooks(ContextHookStage.CONTEXT_TRANSFORM)),
            "after_tool_call": len(self._pipeline.list_hooks(ContextHookStage.AFTER_TOOL_CALL)),
            "before_llm_request": len(self._pipeline.list_hooks(ContextHookStage.BEFORE_LLM_REQUEST)),
        }
        return stats
