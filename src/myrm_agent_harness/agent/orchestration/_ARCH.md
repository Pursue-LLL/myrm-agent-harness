# orchestration/

## Overview

Control-plane LLM signals and middleware runtime hooks. **Not Action Tools** — excluded from `_TOOL_LAYERS`, action-tool counts, and default GeneralAgent Turn1 bind.

| Bucket | Path | Count | Role |
|--------|------|-------|------|
| Orchestration signals | `signals/` | 4 | JSON schemas; orchestrator intercepts tool_calls |
| Runtime hooks | `hooks.py` | 1 | `_completion_check`; CompletionGuard RUNTIME_ONLY |

Action Tools SSOT: [../tool_management/_ARCH.md](../tool_management/_ARCH.md)

## Submodule Index

| Path | Description |
|------|-------------|
| `signals/catalog.py` | Signal name SSOT (`ORCHESTRATION_SIGNAL_NAMES`) |
| `signals/deep_research.py` | DR dispatch/think/finalize schemas |
| `signals/verifier.py` | Verifier `submit_verdict` session factory |
| `hooks.py` | `RUNTIME_HOOK_NAMES` SSOT |
