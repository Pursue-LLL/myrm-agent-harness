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
| file_read_tool.py | Core | File read tool factory: local/MCP/File ID/**vault://** paths, batch reads, line ranges, multimodal | ✅ |
| file_read_handlers.py | Internal | Multimodal/text/vault execution handlers for file_read_tool | ✅ |
| file_read_truncation.py | Internal | Output truncation helpers for file_read_tool | ✅ |
| file_write_tool.py | Core | File write tool (Claude Code compatible). Creates new files with auto File ID resolution (@file_001) | ✅ |
| revert_service.py | Core | File revert service — undo AI file changes; surfaces revertible/skip_reason; skips non-revertible snapshots on revert. | ✅ |
| streaming.py | Core | File streaming reader. Adaptive large-file handling to prevent OOM with configurable StreamingConfig | ✅ |

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
