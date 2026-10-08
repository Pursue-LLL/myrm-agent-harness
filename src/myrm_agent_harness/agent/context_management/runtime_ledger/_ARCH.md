# runtime_ledger

Architecture and module inventory for the `runtime_ledger` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting runtime ledger types, compiler, tail injector, and facade suite |
| `runtime_ledger_types.py` | Domain models and contracts for deterministic runtime state ledger and cache-friendly tail injection |
| `deterministic_ledger_compiler.py` | Deterministic compiler aggregating runtime tool call counters, quota constraints, and task progression |
| `tail_ledger_injector.py` | Tail-positioned status tag serializer and cache-friendly prompt injector for runtime state ledgers |
| `deterministic_runtime_state_ledger_suite.py` | End-to-end facade orchestrating deterministic runtime state ledger compilation and tail injection |
