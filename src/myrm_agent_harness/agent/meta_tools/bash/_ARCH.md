# bash/

## Overview
Bash tool module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Bash tool module. | — |
| _tool_description.py | Internal | Static `TOOL_DESCRIPTION` prompt string for the LLM (split out for file-size hygiene; isolated from wiring). | ✅ |
| _output_eviction.py | Internal | Large output eviction (save to file, return `EvictionResult(text, evicted_ref)` for SSE propagation to GUI viewer). | ✅ |
| _event_logging.py | Internal | Event logging for bash command execution (redaction, classification). | ✅ |
| _preflight_checks.py | Internal | Security preflight: URL exfiltration, sensitive paths, interactive detection. | ✅ |
| output_compressor.py | Internal | Command-aware semantic compressor entry point (Dual-Engine: hardcoded + YAML-driven). Orchestrates compressor registry and DeclarativeFilterEngine. | ✅ |
| _compressors.py | Internal | Concrete command-specific compressors (git, test, package install, docker, build, compiler, log). | ✅ |
| bash_execution_error.py | Core | Structured BashExecutionError with diagnostic previews. | ✅ |
| bash_executor_constants.py | Internal | Shared BashExecutor constants (MCP timeout floor). | — |
| bash_executor.py | Core | BashExecutor aggregate root (DI-based orchestrator). MRO: Execute → Background → Prepare → Context. | ✅ |
| bash_executor_execute_mixin.py | Core | Synchronous ``execute()`` orchestration. | ✅ |
| bash_executor_background_mixin.py | Core | ``spawn_background()`` via background process registry. | ✅ |
| bash_executor_prepare_mixin.py | Core | MCP proxy, code-type detection, skill staging, PTC routing. | ✅ |
| bash_executor_context_mixin.py | Core | ExecutionContext build, OAuth issuer scoping, event logging. | ✅ |
| bash_tool.py | Core | LangChain tool factory. Persistent session, exit code semantics, multimodal image return (capped at MAX_IMAGES_PER_RETURN), `run_in_background` parameter wiring; builds per-spawn finish/progress listeners that bridge registry events to `ptc_notify` and classifies background exit codes (`oom_killed` / `segfault` / `signal_terminated` / `nonzero_exit`) for the UI. | ✅ |
| bash_process_tools.py | Core | LangChain tools `bash_process_list_tool` / `bash_process_output_tool` / `bash_process_kill_tool` that operate on the background process registry. Session-scoped; `session_id=None` fails closed; `bash_process_list_tool` description exposes `last_progress` to the LLM so it can triage stuck workers without a per-pid output fetch; `bash_process_output_tool` supports incremental polling via `since_cursor`. | ✅ |
| _background_types.py | Core | Shared dataclasses & typing aliases (`BackgroundProcessInfo`, `BackgroundQuotaError`, `FinishListener`, `ProgressListener`) consumed by the registry and bash tool wiring. Lives alongside the registry so downstream callers can import the snapshot type without triggering the registry singleton's `atexit` hook. | ✅ |
| _background_registry.py | Core | Process-wide registry (per-session bucket) for background bash jobs; ring-tail stdout/stderr 200 lines with per-line monotonic cursor for incremental polling, per-session concurrency cap (`BackgroundQuotaError`), per-entry finish/progress listeners, SIGTERM→SIGKILL grace escalation in `kill`, per-line 32 KiB hard truncation with `LimitOverrunError` recovery, `call_later`-driven reap of exited entries after a 300 s idle window, `last_progress` snapshot on `BackgroundProcessInfo` so `bash_process_list_tool` exposes per-job percent/message without a per-pid output fetch, `kill_session_jobs(session_id)` for cooperative cleanup invoked by the server when an agent stream is cancelled, and an `atexit` `shutdown` hook that routes through `kill_process_group(SIGKILL)` so forked grandchildren (`node`/`esbuild` under `npm start`, etc.) die with the leader instead of orphaning. | ✅ |
| _background_progress.py | Core | Stateless parser converting one stdout/stderr line into a notify payload. Recognises `MYRM_PROGRESS` / `MYRM_CHECKPOINT` JSON markers plus heuristic patterns (`42%`, `n/m unit`, `Compiling/Building/...` phase); short-circuits lines flagged as error trails (`ERROR`/`ERR!`/`FATAL`/`TRACEBACK`/...) so failure reports never advertise themselves as build progress. | ✅ |
| command_classifier.py | Core | Command classifier. Auto-classifies commands by type (READ/WRITE/DANGEROUS/NETWORK/GIT/SEARCH/PYTHON | ✅ |
| mcp_citation_handler.py | Core | MCP Metadata Extractor | ✅ |
| scripts/resilience_init.sh | Core | Sandbox resilience script injected into BashExecutor for git/npm fallback | ✅ |
| sensitive_parameter_redactor.py | Core | Command parameter redactor. Automatically redacts sensitive parameters (--token, --password, --api-k | ✅ |
| workspace_manager.py | Core | Thin delegation over `WorkspaceService`; lazy instantiation uses aggregate root bound by `toolkits.code_execution.workspace.storage_root_bind` during `setup_workspace`. | ✅ |
| skill_workspace_manager.py | Core | Skill file staging paths under active workspace dirs; resolves `WorkspaceService` using the bound aggregate root. | ✅ |

## Key Dependencies

- `backends`
- `runtime`
- `skills/mcp`
- `toolkits`
- `utils`
