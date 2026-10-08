# hooks/

## Overview
User-configurable lifecycle hook system. Complements middlewares (framework-internal safety logic) by providing external extension points without source code modification.

**Not** `myrm_agent_harness.api.hooks` — that is the server integration facade; see [../../api/_ARCH.md](../../api/_ARCH.md).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | User-configurable lifecycle hook system. Complements middlewares (framework-internal safety logic) by providing external extension points without source code modification. | ✅ |
| executor.py | Core | Hook execution layer. Dispatches hooks from a `HookRegistry` with ContextVar-based session isolation and per-hook elapsed_ms timing. A hook `matcher` is an fnmatch over the runtime tool name; `\|` separates alternatives (`bash_*\|write_file_tool`). Command hooks run through the command gate and receive the event as `$HOOK_EVENT` plus the payload both as the clipped `$HOOK_PAYLOAD` env var and complete on stdin. LLM hooks build the model via `create_litellm_model` (model from hook config or `MYRM_HOOK_MODEL` env). `_parse_hook_json` parses LLM-hook verdicts via `parse_llm_json_object` (robust against fences, prose, bare control chars, trailing commas). `get()` orders hooks by `-priority` (stable ties = onion registration order); security-priority hooks run first and their decisions (block / `updated_input`) are locked against lower-priority overrides (deny→approve flip protection). | ✅ |
| registry.py | Core | `HookRegistry`: event→hooks store. `get()` orders by `-priority` (stable ties = registration order). Hooks can also be registered as a named **scope** (`activate_scope` / `release_scope`, identity-based unregister) so a group — e.g. one skill's hooks — lives for exactly one run and never accumulates or leaks across runs sharing a context. | ✅ |
| command_gate.py | Core | Command hook safety gate + payload binding + approval injection point. Reuses the code_execution static analyzer (`analyze_command`) on the authored command template (never the event payload, so the verdict is identical for every event): BLOCK-level threats (dangerous commands, obfuscation, control characters) refused unconditionally, ESCALATE-level refused for third-party provenance (skill/plugin/user_config — hooks fire silently), built-in hooks keep the wider path. Shell-syntax vectors (`;`, `$()`, `${}`, backticks) and redirects are ordinary in human-authored hooks and are waived. `bind_payload_reference` rewrites `$ARGUMENTS` into a quoting-aware `$HOOK_PAYLOAD` reference so event data never becomes command text (no data→code). `payload_env_value` clips the variable's string values step by step to fit one environment string (`MAX_PAYLOAD_ENV_CHARS`; the OS rejects an oversized environment with E2BIG) while the executor pipes the complete payload to the command's stdin. `set_command_hook_approver` lets the product layer surface an approval card; standalone default is fail-closed for third-party hooks. | ✅ |
| session_access.py | Core | Session-scoped ContextVar access API (get/set_hook_executor, fire_hook, payload_from_dataclass, bootstrap_hook_registry); both import paths (session_access / executor) expose those names, while `has_callable_hook` (named callable-hook presence check used for idempotent framework-hook registration) lives only here. The executor lives in a ContextVar and `fire_hook` is a silent no-op without one, so `run_agent_loop` rebinds it before creating the executor task: a host that advances the stream with a new task per event would otherwise leave the tool loop without any hook. | ✅ |
| output_spiller.py | Core | Hook output spiller. Prevents oversized hook outputs (>2500 tokens) from bloating context by writing to disk. | ✅ |
| graceful_shutdown.py | Core | Graceful shutdown manager. Handles SIGTERM/SIGINT signals, triggers graceful shutdown, and auto-saves checkpoints. Zero-configuration, works out of the box. | ✅ |
| hot_reload.py | Core | Hook hot-reload watcher. Monitors JSON/YAML config file changes and auto-reloads hook definitions without agent restart. Config-loaded hooks are governance-stamped at load time: `source=user_config` and priority capped below the security band, so a config file can never impersonate built-in hooks or outrank safety hooks. | ✅ |
| skill_parser.py | Core | SKILL.md Hook parser — extract hooks from Markdown frontmatter; parsed hooks are tagged `source=skill` so the gate applies the strict path. `tools:` becomes one `\|`-joined matcher (malformed `tools` skips the entry instead of widening it to match-all); `timeout` and `failure_mode` (`fail_open` / `fail_closed`, `-` or `_`) are validated and normalised; each entry is parsed in isolation, so one malformed entry never discards its siblings. Unknown event names (including `PreCompact`, which never fires) are reported with a warning. | ✅ |
| tool_name_mapping.py | Core | Provides map_to_claude_tool_name, map_from_claude_tool_name, should_trigger_hook. | ✅ |
| types.py | Core | Hook type definitions. Re-exports `core/hooks/types.py` (HookEvent, 4 hook variants with `priority`/`source` governance fields, HookResult, payloads, HookRegistryProtocol). | ✅ |

HTTP hooks use `core/security/http/secure_fetch.py` (`secure_request`) for SSRF protection — not a local duplicate.
HTTP hooks support optional HMAC-SHA256 signing (`secret` field → `X-Webhook-Signature: sha256=…` header) and fire-and-forget mode (`fire_and_forget` field → `asyncio.create_task`, notification events don't block the main flow).

## Key Dependencies

- `core/security/http/secure_fetch.py` — HTTP hook outbound SSRF
- `toolkits`
- `utils`
