# bash/

## Overview
Bash tool module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Bash tool module. | — |
| `_tool_description.py` | Internal | Static ~1.4k-char `TOOL_DESCRIPTION` (cache-stable across agents). PTC generic bind-name rules + compact `get_ptc_description()` builtins appendix. | ✅ |
| _output_eviction.py | Internal | Large output eviction (save to file, return `EvictionResult(text, evicted_ref)` for SSE propagation to GUI viewer). | ✅ |
| _event_logging.py | Internal | Event logging for bash command execution (redaction, classification). | ✅ |
| _preflight_checks.py | Internal | Security preflight: URL exfiltration, sensitive paths, interactive detection, install package registry verification (anti-slopsquatting). | ✅ |
| output_compressor.py | Internal | Command-aware semantic compressor entry point (Dual-Engine: hardcoded + YAML-driven). Orchestrates compressor registry and DeclarativeFilterEngine. | ✅ |
| _compressors.py | Internal | Concrete command-specific compressors (git, test, package install, docker, build, compiler, log). | ✅ |
| bash_execution_error.py | Core | Structured BashExecutionError with diagnostic previews. | ✅ |
| bash_executor_constants.py | Internal | Shared BashExecutor constants (MCP timeout floor). | — |
| bash_executor.py | Core | BashExecutor aggregate root (DI-based orchestrator). MRO: Execute → Background → Prepare → Context. | ✅ |
| bash_executor_execute_mixin.py | Core | Synchronous ``execute()`` orchestration. | ✅ |
| bash_executor_background_mixin.py | Core | ``spawn_background()`` via background process registry. | ✅ |
| bash_executor_prepare_mixin.py | Core | MCP proxy, code-type detection, skill staging, PTC routing. | ✅ |
| bash_executor_context_mixin.py | Core | ExecutionContext build, OAuth issuer scoping, event logging. | ✅ |
| bash_code_execute_tool.py | Core | ``create_bash_code_execute_tool`` LangChain factory aggregate root; re-exports test helpers. | ✅ |
| bash_tool_exit_semantics.py | Core | Exit-code semantic interpretation (grep=1, git diff, signals). | ✅ |
| bash_tool_formatting.py | Core | Output compression, truncation, redaction, tool_output wrapping. | ✅ |
| bash_tool_background_listeners.py | Core | Background spawn ptc_notify listeners and exit classification; natural ``exited`` finish emits progress + optional server finish hook; ``killed`` (session cancel) is silent (no finish ptc_notify, no chat persistence). | ✅ |
| bash_tool_multimodal.py | Core | Vision ContentBlock inline return for generated images. | ✅ |
| bash_tool_helpers.py | Core | BashInput schema (`reason` required ≥10 chars, first param), OS hint, context restore, context access tracking. | ✅ |
| _background_job_store_core.py | Core | Pure reconcile/status helpers for BSDL durable ledger. | ✅ |
| _background_job_store.py | Core | SQLite BackgroundJobStore on Volume (metadata, finish dedupe, orphan reconcile). | ✅ |
| _background_output_spill.py | Core | Incremental vault spill for long background stdout/stderr; writes `output_{hex8}.txt` under `.context/{session}/evicted/` (same basename contract as `_output_eviction` + `/files/evicted` API). | ✅ |
| session_spawn_lifecycle.py | Core | Session spawn lifecycle markers; auto-clear when shell jobs exit. | ✅ |
| bash_process_tools.py | Core | Unified LangChain tool ``bash_process_tool`` (actions list/output/kill/wait). ``action=output`` accepts optional ``filter`` regex (via ``_bash_output_filter_core.py``). Turn1 eager when shell enabled (CORE; co-mounted with bash_code_execute). | ✅ |
| _bash_output_filter_core.py | Core | Pure regex line filter for incremental ``bash_process_tool`` output polling (pattern max 256 chars). | ✅ |
| bash_auto_yield.py | Core | Auto-yield foreground whitelist commands into background after ``yield_after_seconds``; composes registry poll snapshot for tool return. | ✅ |
| _background_types.py | Core | Shared dataclasses & typing aliases (`BackgroundProcessInfo`, `BackgroundQuotaError`, `FinishListener`, `ProgressListener`) consumed by the registry and bash tool wiring. Lives alongside the registry so downstream callers can import the snapshot type without triggering the registry singleton's `atexit` hook. | ✅ |
| _background_registry.py | Core | Process-wide registry (per-session bucket) for background bash jobs; ring-tail buffers, per-session concurrency cap (`BackgroundQuotaError`), finish/progress listeners, SIGTERM→SIGKILL grace escalation in `kill`, `call_later`-driven reap, `kill_session_jobs`, `atexit` shutdown, write-through `BackgroundJobStore` registration. Clears session spawn markers via `_maybe_clear_session_spawn_tools` when no running jobs remain. Pipe I/O in `_background_registry_consume.py`; store sync and poll in sibling modules below. | ✅ |
| _background_registry_consume.py | Core | Per-entry stdout/stderr reader loop, spill hooks, terminal persist, finish listener dispatch. | ✅ |
| _background_registry_store_sync.py | Core | Write-through helpers: spawn row upsert, first-spill `vault_log_ref`, terminal state persist. | ✅ |
| _background_registry_poll.py | Core | Incremental poll snapshot builder for ``bash_process_tool`` / auto-yield (cursor + optional regex filter). | ✅ |
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
