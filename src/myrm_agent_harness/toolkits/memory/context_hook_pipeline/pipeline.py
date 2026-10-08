"""Pluggable Context Hook Pipeline orchestrating interceptors across lifecycle stages.

[INPUT]
- memory.context_hook_pipeline.models::{ContextEnvelope, ContextHookStage, HookExecutionPriority, HookExecutionReport} (POS: data contracts of the context hook pipeline package)
- pydantic::{BaseModel, ConfigDict, Field} (POS: validated hook registration record)

[OUTPUT]
- HookCallable: hook signature, receives the envelope and returns whether it modified it
- RegisteredHook: hook id, stage, priority, handler and description
- PluggableContextHookPipeline: registers hooks per stage (re-registering an id replaces it), runs a stage's hooks synchronously in ascending priority order and returns one HookExecutionReport per executed hook; a hook that blocks the envelope or raises ends the stage, and an exception blocks the envelope with the failure reason

[POS]
Synchronous hook chain of the context hook pipeline package, driven stage by stage by the facade.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from myrm_agent_harness.toolkits.memory.context_hook_pipeline.models import (
    ContextEnvelope,
    ContextHookStage,
    HookExecutionPriority,
    HookExecutionReport,
)

# Signature for hook callable: receives envelope, returns True if modified, False otherwise
HookCallable = Callable[[ContextEnvelope], bool]


class RegisteredHook(BaseModel):
    """Metadata and callable reference of a registered hook interceptor."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    hook_id: str
    stage: ContextHookStage
    priority: int = Field(default=int(HookExecutionPriority.USER_CUSTOM))
    handler: HookCallable
    description: str = Field(default="")


class PluggableContextHookPipeline:
    """Orchestrates onion-style context modification across lifecycle stages."""

    def __init__(self) -> None:
        self._hooks: dict[ContextHookStage, list[RegisteredHook]] = {
            stage: [] for stage in ContextHookStage
        }

    def register_hook(
        self,
        hook_id: str,
        stage: ContextHookStage,
        handler: HookCallable,
        priority: int = int(HookExecutionPriority.USER_CUSTOM),
        description: str = "",
    ) -> None:
        """Register an interceptor hook at a specific stage with priority."""
        # Remove existing if same hook_id exists in stage
        self.unregister_hook(hook_id, stage)

        hook = RegisteredHook(
            hook_id=hook_id,
            stage=stage,
            priority=priority,
            handler=handler,
            description=description,
        )
        self._hooks[stage].append(hook)
        # Sort by priority ascending (lower runs earlier)
        self._hooks[stage].sort(key=lambda h: h.priority)

    def unregister_hook(self, hook_id: str, stage: ContextHookStage) -> bool:
        """Remove a hook by identifier from a specific stage."""
        before_len = len(self._hooks[stage])
        self._hooks[stage] = [h for h in self._hooks[stage] if h.hook_id != hook_id]
        return len(self._hooks[stage]) < before_len

    def list_hooks(self, stage: ContextHookStage | None = None) -> list[RegisteredHook]:
        """List registered hooks across all stages or for a specific stage."""
        if stage:
            return list(self._hooks[stage])
        all_hooks: list[RegisteredHook] = []
        for stage_hooks in self._hooks.values():
            all_hooks.extend(stage_hooks)
        return all_hooks

    def execute_stage(
        self,
        stage: ContextHookStage,
        envelope: ContextEnvelope,
    ) -> list[HookExecutionReport]:
        """Execute all registered hooks for the given stage in priority order."""
        reports: list[HookExecutionReport] = []
        stage_hooks = self._hooks[stage]

        for hook in stage_hooks:
            # If a prior hook blocked execution, abort pipeline
            if envelope.is_blocked:
                break

            start_t = time.perf_counter()
            was_modified = False
            try:
                was_modified = hook.handler(envelope)
            except Exception as e:
                envelope.is_blocked = True
                envelope.block_reason = f"Hook '{hook.hook_id}' raised unexpected exception: {e!s}"
                duration_ms = (time.perf_counter() - start_t) * 1000.0
                reports.append(
                    HookExecutionReport(
                        hook_id=hook.hook_id,
                        stage=stage,
                        priority=hook.priority,
                        execution_time_ms=round(duration_ms, 3),
                        was_modified=False,
                        is_blocked=True,
                    )
                )
                break

            duration_ms = (time.perf_counter() - start_t) * 1000.0
            reports.append(
                HookExecutionReport(
                    hook_id=hook.hook_id,
                    stage=stage,
                    priority=hook.priority,
                    execution_time_ms=round(duration_ms, 3),
                    was_modified=was_modified,
                    is_blocked=envelope.is_blocked,
                )
            )

        return reports
