# runtime/

## Overview

Single Agent **instance** survival layer — checkpoint, context lifecycle, quota, doctor, memory
pressure. **Not** the Agent reasoning loop (`agent/`) and **not** generic job queues (`toolkits/tasks/`).

Layer cheatsheet: [ARCHITECTURE.md](../../../ARCHITECTURE.md) §Harness 五层落点.

Detailed design: [CONVERSATION_FORK_SYSTEM.md](CONVERSATION_FORK_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Single Agent instance survival layer exports. | ✅ |

## Subpackages

| Submodule | Description | Doc |
| --- | --- | --- |
| `context/` | Context lifecycle — cleanup, offload, archive, session | [context/_ARCH.md](context/_ARCH.md) |
| `checkpointing/` | Checkpointer factory | [checkpointing/_ARCH.md](checkpointing/_ARCH.md) |
| `events/` | Runtime event bus | [events/_ARCH.md](events/_ARCH.md) |
| `maintenance/` | Global adaptive maintenance scheduling | [maintenance/_ARCH.md](maintenance/_ARCH.md) |
| `quota/` | Storage quota management | [quota/_ARCH.md](quota/_ARCH.md) |
| `install_guard/` | Dual-wheel install readiness | [install_guard/_ARCH.md](install_guard/_ARCH.md) |
| `diagnostics/` | Doctor + compliance self-audit | [diagnostics/_ARCH.md](diagnostics/_ARCH.md) |
| `survival/` | Memory pressure, resource monitor, startup timing | [survival/_ARCH.md](survival/_ARCH.md) |
| `paths/` | Execution path SSOT + compression | [paths/_ARCH.md](paths/_ARCH.md) |
| `artifacts/` | Artifact judge + checkpoint protocol | [artifacts/_ARCH.md](artifacts/_ARCH.md) |
| `fork/` | Conversation fork types | [fork/_ARCH.md](fork/_ARCH.md) |
| `deps/` | Lazy optional dependency install | [deps/_ARCH.md](deps/_ARCH.md) |

## Key Dependencies

- `agent`
- `toolkits`
