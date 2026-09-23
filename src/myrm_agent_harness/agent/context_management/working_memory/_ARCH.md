# working_memory/

## Overview
Local Working Memory Block subsystem providing low-overhead, in-memory execution state tracking (active goal, subtasks progression, scratchpad memos, and transient error-avoidance traps).
Strictly adheres to Prompt Cache Safety by injecting state exclusively into Dynamic Turn Tail without mutating static system prompt prefixes.

## File Index

| File | Role | Description |
|------|------|-------------|
| `types.py` | Data Models | SSOT dataclasses and enums: `SubtaskStatus`, `SubtaskItem`, `TrapRecord`, `LocalWorkingState`, and `WorkingMemoryFlushResult`. |
| `marks.py` | Marks Metadata Contract | `WorkingMemoryMark` enum, `IMMUNE_MARKS` set, and message-level mark manipulation (with/remove), inspection, and immunity primitives. |
| `block.py` | Working Block Controller | `LocalWorkingMemoryBlock` class backed by `ContextVar` providing goal tracking, subtask updates, trap logging, snapshotting, token estimation, FIFO smooth flush (`flush_stale`), and prompt cache-safe turn-tail sliding rendering. |
| `__init__.py` | Package Exports | Canonical public exports for harness runtime and context management layers. |

## Key Invariants
1. **Prompt Cache Safety**: Working board representations attach strictly to the dynamic suffix/tail of the current turn (`<working_board>`). They NEVER mutate static system prompt prefixes.
2. **Context Isolation**: Backed by `ContextVar`, ensuring complete thread and async task isolation across concurrent sessions.
3. **Zero-LLM Overhead**: All operations (initialization, subtask transitions, deduplicated trap records) execute in pure Python memory without invoking external models.
