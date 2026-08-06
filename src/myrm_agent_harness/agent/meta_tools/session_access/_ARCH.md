# session_access/

## Overview

Agent meta-tools for HITL session directory access grants. The agent calls `request_directory_tool` when it needs files outside the current workspace roots; the server emits a `directory_request_required` SSE event, and the frontend renders an approval card for the user.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `request_directory.py` | Core | Pydantic schema: `RequestDirectoryInput` (reason, path, writable) | ✅ |
| `request_directory_tool.py` | Core | `RequestDirectoryTool` LangChain adapter + `create_request_directory_tool` factory | ✅ |
| `__init__.py` | Package | Public exports: `RequestDirectoryInput`, `create_request_directory_tool` | ✅ |

## Key Dependencies

- Server: `tool_setup._setup_session_access_tools` injects interrupt callback via `_on_request_directory` closure; `session_access_service.py` handles persistence + deployment boundary gate (`is_directory_grant_allowed_for_deployment` gates sandbox/cloud/local).
- Server: `stream_collector.py` collects `directory_request_required` SSE events; `stream_finalize.py` manages timeout + answered state.
- Harness: `security/session_access.py` provides runtime ContextVar (`get/set/grant/revoke_session_access_roots`) + `merge_path_policy_with_session_access` for turning grants into enforceable `PathPolicy`.
- Harness: `SessionAccessMiddleware` renders available directories into the agent prompt each turn.
- Frontend: generic interrupt/approval flow handles the directory request card.
