# tools/

## Overview
API layer of the browser toolkit. Maps BrowserSession capabilities to 8 LangChain @tool functions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | API layer of the browser toolkit. Maps BrowserSession capabilities to 8 LangChain @tool functions. | ✅ |
| _semantic_risk.py | Internal | Semantic DOM risk classification (ARIA role+name + JS eval patterns). Consumed by semantic_dom_hitl.py. | ✅ |
| semantic_dom_hitl.py | Internal | Shared LangGraph HITL gate for session.interact, browser_interact_tool, and evaluate paths. | ✅ |
| common.py | Core | Shared utilities for browser tools. | ✅ |
| execute_script.py | Core | browser_execute_script_tool: Code-as-Action batch execution with AST privileged-API scanner + HITL gating. | ✅ |
| extract.py | Core | browser_extract_tool: content extraction. | ✅ |
| inspect.py | Core | browser_inspect_tool: quick page structure analysis. | ✅ |
| interact.py | Core | browser_interact_tool: element interactions with optional steps[] batch + semantic DOM risk check (HITL for destructive/financial/admin actions). | ✅ |
| manage.py | Core | browser_manage_tool: session management (HITL via browser_ask_human_tool; no wait_for_user). | ✅ |
| navigate.py | Core | browser_navigate_tool: URL navigation; success path appends ≤20 compact interactive refs. | ✅ |
| snapshot.py | Core | browser_snapshot_tool: ARIA tree capture. | ✅ |
| takeover.py | Core | browser_ask_human_tool: Agent-triggered human takeover via LangGraph interrupt; SSE includes runtime `is_managed` (managed→VNC, external/CDP→in-chat banner). | ✅ |

## Key Dependencies

- `utils`
- `snapshot` (RefInfo for semantic risk classification)
- `langgraph.types` (interrupt/resume for HITL)
