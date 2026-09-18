# cognitive_clock/

## Overview

Framework-level multi-frequency cognitive clock scheduling primitives (T0-T3 cadences) and cooperative yielding signals, based on the HOPE nested learning architecture.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Entry | Public exports for cadences, pause signals, and in-memory clock bus | ✅ |
| `cadence.py` | Core | Four-tier `CognitiveCadence` enum and immutable clock tick/task specs | ✅ |
| `signals.py` | Core | Re-export of `infra/cooperative_signals.py` (single shared singleton). `toolkits/` imports from `infra/`, never from here. | ✅ |
| `bus.py` | Core | In-memory `CognitiveClockBus` dispatcher respecting cooperative pauses | ✅ |

## Key Dependencies

- Pure standard library (`dataclasses`, `enum`, `asyncio`, `time`)
- Self-contained, framework-agnostic, zero external package dependencies
