# bash/

## Overview
Bash tool module.

## Bash Python routing (SSOT)

| Need | Use | Do not use |
|------|-----|------------|
| Single tool call | Native LangChain tools (`file_read_tool`, …) | bash / `myrm_tools` |
| MCP batch script | `from skills.* import …` | `myrm_tools` |
| Cross-bash persistence | `/workspace` JSON files / `file_write_tool` | Paste JSON into chat / `myrm_tools` |
| Long-script progress | `MYRM_PROGRESS` echo (see `TOOL_DESCRIPTION`) | `myrm_tools.notify` |
| Orchestration spawn/notify | Dynamic Workflow → `myrm_tools.*` | Regular bash |

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Bash tool module. | — |
| `_tool_description.py` | Internal | Static cache-stable `TOOL_DESCRIPTION`: capabilities, merge/OBSERVATION rules, native-tool routing, background jobs (`waiting_for_input`/`submit_stdin`, eviction read hint, `run_in_background=true` forbids trailing `&`); internal-module names omitted (`myrm_tools` guard in `_preflight_checks`). | ✅ |
| _output_eviction.py | Internal | Large output eviction (save to file, return `EvictionResult(text, evicted_ref)` for SSE propagation to GUI viewer). Triggered by token threshold (20k) **or** char threshold aligned with `truncate_bash_output` (8k), so any output that would be hard-truncated is first persisted on disk. Shared by stdout and stderr streams (`bash_executor_execute_mixin` evicts them symmetrically, one evicted file + GUI ref per stream). | ✅ |
| _event_logging.py | Internal | Event logging for bash command execution (redaction, classification). Failure-path stdout/stderr are evicted before logging, so the log only ever holds bounded previews. | ✅ |
| `_preflight_checks.py` | Internal | Security preflight: URL exfiltration, sensitive paths, myrm_tools guard (AST / bash `-c` / `-m` / pipe stdin / cat\|pipe `.py` scan / referenced `.py` scan; raises ``ToolError`` with ``MYRM_TOOLS_BLOCKED`` + ``guardrail_blocked`` for GUI Badge), interactive detection, install package registry verification. | ✅ |
| output_compressor.py | Internal | Command-aware semantic compressor entry point (Dual-Engine: hardcoded + YAML-driven). Orchestrates compressor registry and DeclarativeFilterEngine. Skips any stdout that is already an eviction preview (banner-prefixed) so the `file_read_tool` read-back footer survives the format pipeline. | ✅ |
| _compressors.py | Internal | Concrete command-specific compressors (git, test, package install, docker, build, compiler, log). | ✅ |
| bash_execution_error.py | Core | Structured BashExecutionError carrying stdout/stderr eviction references (failure-path large streams persisted and read-back via ``file_read_tool``). | ✅ |
| bash_executor_constants.py | Internal | Shared BashExecutor constants (MCP timeout floor). | — |
| bash_executor.py | Core | BashExecutor aggregate root (DI-based orchestrator). MRO: Execute → Background → Prepare → Context. | ✅ |
| bash_executor_execute_mixin.py | Core | Synchronous ``execute()`` orchestration; symmetric stdout/stderr eviction (each stream independently persisted when large, with separate ``evicted_ref``/``stderr_evicted_ref`` for the GUI drawer); failure path evicts both streams, logs the evicted text (bounded, never the raw stream), appends stdout then stderr previews/footers to the error message so the LLM sees the full traceback and partial stdout context, then raises ``BashExecutionError`` carrying both streams' eviction refs; post-bash ``OfficeBashAudit`` fidelity warnings. | ✅ |
| bash_executor_background_mixin.py | Core | ``spawn_background()`` via background process registry; strips a bare trailing ``&`` (``&&`` preserved) so ``sh -c`` cannot orphan the spawned process. | ✅ |
| bash_executor_prepare_mixin.py | Core | MCP proxy, code-type detection, skill staging. | ✅ |
| bash_executor_context_mixin.py | Core | ExecutionContext build, OAuth issuer scoping, event logging. | ✅ |
| bash_code_execute_tool.py | Core | ``create_bash_code_execute_tool`` LangChain factory; static TOOL_DESCRIPTION + OS hint; preflight ``ToolError`` re-raised (preserves ``guardrail_blocked`` for SSE); ``BashExecutionError`` wrapped (its evicted stderr ref emitted so the GUI drawer stays reachable on failure). Emits both stdout and stderr evicted refs (``stream`` marker distinguishes them for the GUI). | ✅ |
| bash_tool_exit_semantics.py | Core | Exit-code semantic interpretation (grep=1, git diff, signals). | ✅ |
| bash_tool_formatting.py | Core | Output compression, truncation, redaction, tool_output wrapping. Exposes `BASH_OUTPUT_MAX_CHARS` (single source of truth for the 8k hard-truncation limit; `_output_eviction` reuses it as its char-level eviction gate). | ✅ |
| bash_tool_background_listeners.py | Core | Background spawn ptc_notify listeners and exit classification; natural ``exited`` finish emits progress + optional server finish hook; ``killed`` (session cancel) is silent (no finish ptc_notify, no chat persistence). | ✅ |
| bash_tool_multimodal.py | Core | Vision ContentBlock inline return for generated images. | ✅ |
| bash_tool_helpers.py | Core | BashInput schema (`reason` required ≥10 chars, first param), OS hint, context restore, context access tracking. | ✅ |
| session_spawn_lifecycle.py | Core | Session spawn lifecycle markers; auto-clear when shell jobs exit. | ✅ |
| bash_process_tools.py | Core | Unified LangChain tool ``bash_process_tool`` (actions list/output/kill/wait/write_stdin/submit_stdin/close_stdin). ``action=output`` / ``wait`` (still running) expose ``waiting_for_input`` + ``input_wait_hint`` when idle; tool/Field descriptions and ``TOOL_DESCRIPTION`` SSOT the submit_stdin response contract. ``action=output`` accepts optional ``filter`` regex (via ``_bash_output_filter_core.py``). Turn1 eager when shell enabled (CORE; co-mounted with bash_code_execute). stdin/kill actions require ``shell_exec`` HITL permission. | ✅ |
| _bash_output_filter_core.py | Core | Pure regex line filter for incremental ``bash_process_tool`` output polling (pattern max 256 chars). | ✅ |
| bash_auto_yield.py | Core | Auto-yield foreground whitelist commands into background after ``yield_after_seconds``; composes registry poll snapshot for tool return. | ✅ |
| _background/ | Submodule | Background bash job registry, durable ledger, stdout spill, progress parsing. See [_background/_ARCH.md](_background/_ARCH.md). | ✅ |
| command_classifier.py | Core | Command classifier. Auto-classifies commands by type (READ/WRITE/DANGEROUS/NETWORK/GIT/SEARCH/PYTHON | ✅ |
| mcp_citation_handler.py | Core | MCP Metadata Extractor | ✅ |
| scripts/resilience_init.sh | Core | Sandbox resilience script injected into BashExecutor: git/npm fallbacks, GitHub push credential (host-scoped) + commit identity injection | ✅ |
| sensitive_parameter_redactor.py | Core | Command parameter redactor. Automatically redacts sensitive parameters (--token, --password, --api-k | ✅ |
| workspace_manager.py | Core | Thin delegation over `WorkspaceService`; lazy instantiation uses aggregate root bound by `toolkits.code_execution.workspace.storage_root_bind` during `setup_workspace`. | ✅ |
| skill_workspace_manager.py | Core | Skill file staging paths under active workspace dirs; resolves `WorkspaceService` using the bound aggregate root. | ✅ |

## Key Dependencies

- `backends`
- `runtime`
- `skills/mcp`
- `toolkits`
- `utils`
