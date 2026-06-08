# tools/

## Overview
API layer of the browser toolkit. Maps BrowserSession capabilities to 7 LangChain @tool functions,

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | API layer of the browser toolkit. Maps BrowserSession capabilities to 7 LangChain @tool functions, | ✅ |
| _semantic_risk.py | Internal | Semantic DOM risk classification. Classifies element interactions as safe/high-risk based on ARIA role+name. Used by interact.py for HITL gating. | ✅ |
| common.py | Core | Shared utilities for browser tools. | ✅ |
| execute_script.py | Core | browser_execute_script_tool: Code-as-Action batch execution. | ✅ |
| extract.py | Core | browser_extract_tool: content extraction content extraction. | ✅ |
| inspect.py | Core | browser_inspect_tool: quick page structure analysis quick page structure analysis. | ✅ |
| interact.py | Core | browser_interact_tool: element interactions with semantic DOM risk check (HITL for destructive/financial/admin actions). | ✅ |
| manage.py | Core | browser_manage_tool: session management session management. | ✅ |
| navigate.py | Core | browser_navigate_tool: URL navigation URL navigation. | ✅ |
| snapshot.py | Core | browser_snapshot_tool: ARIA tree capture ARIA tree capture. | ✅ |

## Key Dependencies

- `utils`
- `snapshot` (RefInfo for semantic risk classification)
