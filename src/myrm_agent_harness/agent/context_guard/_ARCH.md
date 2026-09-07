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
