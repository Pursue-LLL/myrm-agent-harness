"""Cognitive cadence definitions for nested multi-frequency clock.

[INPUT]
- None (pure protocol / enum primitives)

[OUTPUT]
- CognitiveCadence: Enum defining HOPE/Nested Learning 4-tier cadences (T0-T3).
- CognitiveClockTaskSpec: Specifications for tasks bound to a specific cadence.
- CognitiveClockTickEvent: Data carrier emitted on clock ticks.

[POS]
Harness runtime tier. Pure engine primitives, strictly business-agnostic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class CognitiveCadence(StrEnum):
    """Four-tier nested cognitive clock cadences based on HOPE cognitive architecture."""

    T0_MICRO_STEP = "t0_micro_step"  # Millisecond step level: in-memory working scratchpad, turn tail
    T1_MESO_SESSION = "t1_meso_session"  # Second session level: post-session reflection, single-flight debounce
    T2_MACRO_IDLE = "t2_macro_idle"  # Hour idle level: conflict resolution, blindspot harvesting, backup
    T3_EPOCH_MACRO = "t3_epoch_macro"  # Week macro level: cross-session pattern discovery & skill synthesis


@dataclass(frozen=True, slots=True)
class CognitiveClockTaskSpec:
    """Specification of an evolutionary task scheduled at a specific cadence."""

    task_id: str
    cadence: CognitiveCadence
    name: str
    description: str
    interval_seconds: float
    max_execution_seconds: float = 300.0


@dataclass(frozen=True, slots=True)
class CognitiveClockTickEvent:
    """Event emitted whenever a cognitive clock tick is triggered."""

    cadence: CognitiveCadence
    tick_id: str
    timestamp: float = field(default_factory=time.time)
    forced: bool = False
    source: str = "scheduler"
