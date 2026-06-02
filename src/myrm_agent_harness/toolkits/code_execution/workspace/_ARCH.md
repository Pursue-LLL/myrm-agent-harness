# workspace/

## Overview
Workspace module for code execution sessions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Workspace module for code execution sessions. | — |
| models.py | Core | Workspace data models for code execution sessions. | ✅ |
| service.py | Core | Workspace lifecycle; `WorkspaceService` under caller-supplied aggregate root; factory `create_workspace_service(*, root_dir=…)` requires an explicit filesystem root (no cwd default). | ✅ |
| storage_root_bind.py | Core | ContextVar binding of aggregate workspace root for lazy ``WorkspaceService`` construction (from ``merged_context["workspaces_storage_root"]``). ``bind_workspace_storage_root`` returns a ContextVar undo ``Token`` — host code in ``agent._internals.run_lifecycle`` stashes it outside ``merged_context`` so LangGraph/msgpack checkpointing never sees it. | ✅ |

## 相关测试

| 文件 | 说明 |
|------|------|
| `tests/toolkits/code_execution/test_storage_root_bind.py` | `bind_workspace_storage_root` / `release_workspace_storage_bind_token` / `workspace_storage_fs_root_strict` |
