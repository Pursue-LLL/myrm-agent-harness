# session/

## Overview
Persistent Session Module — Maintains long-running shell processes that preserve
state (env vars, cwd) across commands.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports all public API | — |
| persistent_session.py | Core | Abstract `PersistentSession` base class: state machine, execute, stream, auto-recovery, shield-protected cleanup; per-command random markers + `bash -n` syntax gate + script materialization armor with `is_armored` metadata propagation; startup orphan GC via `sweep_stale_materialized_scripts`; wedge self-heal (timeout / corrupted boundary → kill group + TERMINATED) | ✅ |
| local_session.py | Core | `LocalPersistentSession` concrete implementation with bwrap sandbox support and strict child process credential token isolation via `sanitize_env` | ✅ |
| shell_flavor.py | Core | Platform-specific shell drivers: `BashFlavor` (with `exit()` interceptor + block-rc wrapper + errexit `EXIT` trap + ANSI-C `$'…'` env quoting), `PowerShellFlavor` (with UTF-8 console I/O encoding, `$ProgressPreference='SilentlyContinue'`, `exit()` interceptor, dual exit code normalization), `WindowsFlavor` (legacy cmd.exe fallback) | ✅ |
| stream_output_processor.py | Core | `StreamOutputProcessor` — unified tee writing, SSE throttle/valve, disk quota | ✅ |
| stream_buffer.py | Core | `ExecutionStreamBuffer` — zero-copy byte stream parsing with marker detection; `parse_failed` flag when the exit-code field is not a number (boundary corruption) | ✅ |
| log_distiller.py | Core | High-efficiency terminal execution log distiller (`DistilledLogResult`, `TerminalLogDistiller`, `distill_terminal_output`) | ✅ |

## Key Dependencies

- `utils.text_utils.strip_ansi` — ANSI escape sequence stripping for clean SSE output
- `executors.common.exit_classify` — Non-zero exit code semantic classification
- `executors.models.scrub_sensitive_info` — PII scrubbing for real-time SSE streams
- `security.script_armor.prepare_armored_command` — Script materialization & subprocess invocation armor
- `security.script_armor.sweep_stale_materialized_scripts` — Stale orphan temporary script cleanup on startup
