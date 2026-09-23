# observability/debug_bundle/

## Overview

Session debug dossier assembler plus single-variable rerun verdict. Composes
audit trail entries, memory retrieval traces, failure summaries, and config
snapshots into one redacted bundle; reruns a caller-supplied runner with
exactly one config key overridden.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports assembler, rerun helper, and types. | ✅ |
| `types.py` | Core | DebugBundle / BundleSection / RerunComparison DTOs (stdlib dataclasses). | ✅ |
| `assembler.py` | Core | `assemble_debug_bundle` — redact, cap size, seal, gate required sections. | ✅ |
| `rerun.py` | Core | `single_variable_rerun` — one-key override verdict (caller injects runner). | ✅ |

## Key Dependencies

- `observability/audit_trail` (collector, redactor)
- No `agent/`, `eval/`, or `toolkits/` imports — callers supply plain data.
