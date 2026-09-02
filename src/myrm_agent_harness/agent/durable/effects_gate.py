"""Effects boundary and manual drive test hook interface.

[INPUT]
- .types::IntentRecord
- .protocols::EffectsBoundaryProtocol

[OUTPUT]
- DriveMode: AUTOMATIC or MANUAL mode.
- ManualDriveBreakCondition: Callable predicate determining when to inject a simulated crash.
- ManualDriveEffectsGate: Intercepts before/after execution hooks for deterministic crash matrix tests.

[POS]
Effects boundary enabling mechanical step-by-step crash injection and resume validation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from myrm_agent_harness.agent.durable.protocols import EffectsBoundaryProtocol
from myrm_agent_harness.agent.durable.types import IntentRecord


class DriveMode(str, Enum):
    """Execution drive mode."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class SimulatedCrashError(RuntimeError):
    """Simulated process termination / crash injected during testing."""
    pass


class ManualDriveEffectsGate(EffectsBoundaryProtocol):
    """Effects gate supporting step breakpoints and crash simulation."""

    def __init__(self, mode: DriveMode = DriveMode.AUTOMATIC) -> None:
        self.mode = mode
        self.recorded_intents: list[IntentRecord] = []
        self.recorded_results: list[tuple[IntentRecord, Any]] = []
        self._break_on_intent_id: str | None = None
        self._break_on_effect_type: str | None = None
        self._crash_before_effect: bool = False
        self._crash_after_effect: bool = False

    def inject_crash_before_effect(self, effect_type: str | None = None) -> None:
        """Configure the gate to simulate a hard crash right after intent is written, before effect runs."""
        self._crash_before_effect = True
        self._break_on_effect_type = effect_type

    def inject_crash_after_effect(self, effect_type: str | None = None) -> None:
        """Configure the gate to simulate a hard crash right after effect runs, before result entry is appended."""
        self._crash_after_effect = True
        self._break_on_effect_type = effect_type

    def reset_traps(self) -> None:
        """Reset all crash traps."""
        self._crash_before_effect = False
        self._crash_after_effect = False
        self._break_on_effect_type = None
        self._break_on_intent_id = None

    async def before_effect(self, intent: IntentRecord) -> None:
        """Intercept before effect execution."""
        self.recorded_intents.append(intent)
        if self._crash_before_effect:
            if not self._break_on_effect_type or self._break_on_effect_type == intent.effect_type.value:
                self._crash_before_effect = False
                raise SimulatedCrashError(f"Simulated Crash before effect {intent.effect_type.value} on intent {intent.intent_id}")

    async def after_effect(self, intent: IntentRecord, result: Any) -> None:
        """Intercept after effect execution."""
        self.recorded_results.append((intent, result))
        if self._crash_after_effect:
            if not self._break_on_effect_type or self._break_on_effect_type == intent.effect_type.value:
                self._crash_after_effect = False
                raise SimulatedCrashError(f"Simulated Crash after effect {intent.effect_type.value} on intent {intent.intent_id}")
