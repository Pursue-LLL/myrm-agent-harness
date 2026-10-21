# tools/

## Overview
API layer of the browser toolkit. Maps BrowserSession capabilities to 8 LangChain @tool functions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | API layer of the browser toolkit. Maps BrowserSession capabilities to 8 LangChain @tool functions. | ✅ |
| _semantic_risk.py | Internal | Browser-layer semantic DOM risk classification — browser action preconditions (click/dblclick/check/uncheck mutations, key activation, implicit submit) and JS eval patterns layered on the shared cross-channel lexicon from `core.security.detection.semantic_risk` (SSOT shared with desktop AX gates). Consumed by semantic_dom_hitl.py. | ✅ |
| semantic_dom_hitl.py | Internal | Shared LangGraph HITL gate for session.interact, browser_interact_tool, and evaluate paths with key activation propagation; fail-closed when no graph context is available. | ✅ |
| cancel_boundary.py | Core | `apply_cancel_boundary`: wraps every tool coroutine in place. Before each action it heals a tab whose renderer crashed (`active_tab_crashed` → `recover_active_tab`), so the model does not hit a dead page on every call. A stopped run aborts the in-flight browser action within ~0.25s (`run_until_cancelled`), heals the tab (`recover_active_tab`) and returns `CANCELLED_RESULT` instead of an error. A run torn down without the token (executor timeout, stuck-task watchdog, shutdown) heals the tab too, then lets the cancellation continue. A healed tab is blank, so the next text result is prefixed once with the session's reset notice (`take_tab_reset_notice`). No-op outside an agent run (no cancellation token). Applied by both tool factories (`create_browser_tools`, `create_restricted_ax_browser_tools`). | ✅ |
| common.py | Core | Shared utilities for browser tools. `mark_untrusted`: unified output security boundary (credential redaction + untrusted-content wrapping) for every browser tool result. | ✅ |
| execute_script.py | Core | browser_execute_script_tool: Code-as-Action batch execution with AST privileged-API scanner + HITL gating. Output redacted + wrapped via mark_untrusted. | ✅ |
| extract.py | Core | browser_extract_tool: content extraction. | ✅ |
| inspect.py | Core | browser_inspect_tool: quick page structure analysis. Output redacted + wrapped via mark_untrusted. | ✅ |
| interact.py | Core | browser_interact_tool: element interactions with optional steps[] batch + NavPostActionGuard (cross-page hard navigation halt) + semantic DOM risk check (HITL for destructive/financial/admin actions). Supports coordinate mode (x/y parameters) for canvas/rich-editor pages. Output redacted + wrapped via mark_untrusted. | ✅ |
| manage.py | Core | browser_manage_tool: session management + domain skill execution (run_site_tool/list_site_tools). Actions include runtime mobile device emulation (`emulate`, via DeviceEmulator). HITL via browser_ask_human_tool; no wait_for_user. All page-sourced outputs (evaluate/console/network/domain skill) redacted + wrapped via mark_untrusted. | ✅ |
| navigate.py | Core | browser_navigate_tool: URL navigation; Dynamic Hints for web_search/web_fetch when mounted; success path appends ≤20 compact interactive refs. Output redacted + wrapped via mark_untrusted. | ✅ |
| snapshot.py | Core | browser_snapshot_tool: ARIA tree capture. Auto-detects canvas/rich-editor visual content and appends [VISUAL_CONTENT_DETECTED] hint to guide agents toward coordinate mode. | ✅ |
| takeover.py | Core | browser_ask_human_tool: Agent-triggered human takeover via LangGraph interrupt; SSE includes runtime `is_managed` (managed→VNC, external/CDP→in-chat banner). Result (post URL / page title / user message) redacted + wrapped via mark_untrusted. | ✅ |

## Key Dependencies

- `utils`
- `snapshot` (RefInfo for semantic risk classification)
- `langgraph.types` (interrupt/resume for HITL)
