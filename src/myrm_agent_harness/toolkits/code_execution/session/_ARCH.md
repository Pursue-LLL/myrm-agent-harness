# session/

## Overview
Persistent Session Module — Maintains long-running shell processes that preserve
state (env vars, cwd) across commands.

## File & Submodule Index

| File | Role | Description |
|------|------|-------------|
| __init__.py | Package | Re-exports all public API |
| persistent_session.py | Core | Abstract `PersistentSession` base class: state machine, execute, stream, auto-recovery, shield-protected cleanup |
| local_session.py | Core | `LocalPersistentSession` concrete implementation with bwrap sandbox support |
| shell_flavor.py | Core | Platform-specific shell drivers: `BashFlavor`, `WindowsFlavor` |
| stream_output_processor.py | Core | `StreamOutputProcessor` — unified tee writing, SSE throttle/valve, disk quota |
| stream_buffer.py | Core | `ExecutionStreamBuffer` — zero-copy byte stream parsing with marker detection |

## Key Dependencies

- `utils`
- `executors.common.exit_classify` — Non-zero exit code semantic classification
- `executors.models.scrub_sensitive_info` — PII scrubbing for real-time SSE streams
