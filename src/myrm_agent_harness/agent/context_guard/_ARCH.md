# Context Guard and Transparent Spillover Architecture

[INPUT]
- `myrm_agent_harness.agent.context_guard.types`: SpilloverPayload, SpilloverResult, ContextGuardConfig
- `pathlib.Path`: Filesystem path management
- `hashlib.sha256`: Integrity verification

[OUTPUT]
- `SpilloverEngine`: Engine for atomic extraction of context bombs into local file paths.
- `EphemeralTransientSweeper`: 24-hour cleanup sweeper for ephemeral spillover files.

[POS]
Harness-level context safety subsystem preventing LLM context window explosions
by gracefully converting oversized payloads (>16,000 chars) into referenced files.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public re-exports for the context guard engine, sweeper, and config/payload types. | ✅ |
| types.py | Core | Context guard data models (`ContextGuardConfig`, `SpilloverPayload`, `SpilloverResult`) and `estimate_token_pressure`. | ✅ |
| spillover_engine.py | Core | `SpilloverEngine` — atomic extraction of context bombs into local file paths with sha256 integrity verification. | ✅ |
| sweeper.py | Core | `EphemeralTransientSweeper` — 24-hour cleanup sweeper for ephemeral spillover files. | ✅ |
