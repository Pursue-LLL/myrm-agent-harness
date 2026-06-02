# file_ops/

## Overview
File operations tool module (Claude Code compatible).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | File operations tool module (Claude Code compatible). | — |
| constants.py | Core | Constants. | ✅ |
| executor_storage_adapter.py | Core | CodeExecutor to StorageProvider adapter. | ✅ |
| file_edit_tool.py | Core | File edit tool (Claude Code compatible). Supports precise search-and-replace text editing with auto  | ✅ |
| file_read_tool.py | Core | File read tool (Claude Code compatible). Supports multiple path formats (local, MCP, File ID), batch | ✅ |
| file_write_tool.py | Core | File write tool (Claude Code compatible). Creates new files with auto File ID resolution (@file_001) | ✅ |
| incremental_read_tool.py | Core | Incremental log reader tool. Reads file content incrementally from a start_offset, preventing token  | ✅ |
| revert_service.py | Core | File revert service — undo AI file changes at message or file granularity. | ✅ |
| streaming.py | Core | File streaming reader. Adaptive large-file handling to prevent OOM with configurable StreamingConfig | ✅ |
| vault_tools.py | Core | Vault Tools | ✅ |

| Submodule | Description |
|-----------|-------------|
| core/ | Text Editor core business logic module. |
| observers/ | Observers module. |
| strategies/ | File system strategy module. |
| utils/ | Utility functions module. |
| validators/ | Validators module. |

## Key Dependencies

- `backends`
- `toolkits`
- `utils`
