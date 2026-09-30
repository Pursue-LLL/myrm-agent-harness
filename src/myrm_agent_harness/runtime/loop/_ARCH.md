# runtime/loop/

## Overview

Session-scoped recurring loop scheduling runtime algorithms and models.
Pure stateless algorithms for command parsing, noise-stripped semantic fingerprinting,
and adaptive exponential backoff pacing.

Layer cheatsheet: [ARCHITECTURE.md](../../../ARCHITECTURE.md) §Harness 五层落点.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `types.py` | Models | `LoopMode`, `LoopStatus`, `LoopStopReason`, `LoopConfig`, `LoopState` DTOs. | ✅ |
| `parser.py` | Parser | `/loop` command syntax parser, interval formatter, and wakeup prompt builder. | ✅ |
| `fingerprint.py` | Hash | `SemanticFingerprintExtractor` with temporal & dynamic noise removal. | ✅ |
| `backoff.py` | Calculator | `AdaptiveBackoffCalculator` for self-paced exponential backoff with alert bypass. | ✅ |
| `__init__.py` | Package | Public exports for runtime loop package. | ✅ |

## Design Constraints

1. **Pure Stateless Execution**: No database, network, or server dependencies.
2. **Deterministic Noise Filtering**: Strips timestamps, durations, and iteration headers before hashing to prevent measurement decay.
3. **Prompt Cache Protection**: Wakeup prompts follow fixed prefix templates; stops without mutating system prompts.
