"""Context lifecycle hook registration.

[INPUT]
- collections.abc::Callable (POS: Python callable protocol)
- typing::Protocol (POS: Python structural typing protocol)

[OUTPUT]
- ContextLifecyclePhase: OpenClaw-compatible lifecycle phases
- ContextLifecycleHooks: registration-only hook registry

[POS]
Parallel to OpenClaw context-engine lifecycle (bootstrap/assemble/afterTurn/maintain) without
embedding engine implementations inside ContextBundle (#1 scope).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class ContextLifecyclePhase(StrEnum):
    BOOTSTRAP = "bootstrap"
    ASSEMBLE = "assemble"
    AFTER_TURN = "after_turn"
    MAINTAIN = "maintain"


LifecycleHook = Callable[[], Awaitable[None]]


class ContextLifecycleHook(Protocol):
    phase: ContextLifecyclePhase

    async def run(self) -> None: ...


@dataclass
class ContextLifecycleHooks:
    """Registration-only lifecycle hooks for context engines."""

    _hooks: dict[ContextLifecyclePhase, list[LifecycleHook]] = field(default_factory=dict)

    def register(self, phase: ContextLifecyclePhase, hook: LifecycleHook) -> None:
        self._hooks.setdefault(phase, []).append(hook)

    async def run_phase(self, phase: ContextLifecyclePhase) -> None:
        for hook in self._hooks.get(phase, []):
            await hook()
