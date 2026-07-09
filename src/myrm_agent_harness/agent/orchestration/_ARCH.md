# orchestration/

## Overview

Control-plane LLM signals and middleware runtime hooks. **Not Action Tools** — excluded from `_TOOL_LAYERS`, action-tool counts, and default GeneralAgent Turn1 bind.

PTC runtime tools (`spawn_subagent`, `notify`) live in [../dynamic_workflow/_ARCH.md](../dynamic_workflow/_ARCH.md), not here.

| Bucket | Path | Count | Role |
|--------|------|-------|------|
| Orchestration signals | `signals/` | 4 | JSON schemas; orchestrator intercepts tool_calls |
| Runtime hooks | `hooks.py` | 1 | `_completion_check`; CompletionGuard RUNTIME_ONLY |

Action Tools SSOT: [../tool_management/_ARCH.md](../tool_management/_ARCH.md)

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Core | Public re-exports: `ORCHESTRATION_SIGNAL_NAMES`, `RUNTIME_HOOK_NAMES`, `is_runtime_hook` | ✅ |
| hooks.py | Core | `RUNTIME_HOOK_NAMES` SSOT; `is_runtime_hook` for CompletionGuard | ✅ |

## Submodule Index

| Path | Description |
|------|-------------|
| `signals/` | Orchestration signal schemas · [signals/_ARCH.md](signals/_ARCH.md) |
