# tests/scripts/

## Overview

Unit tests for `scripts/` maintenance tooling (tool registry engine/models/validator, file line-limit gate). Architecture gate tests for the same scripts live under `tests/architecture/`.

## File Index

| File | Role | Description |
|------|------|-------------|
| `test_tool_registry_engine.py` | Unit | `scripts/tool_registry_engine.py` scan behavior |
| `test_tool_registry_models.py` | Unit | `scripts/tool_registry_models.py` DTO validation |
| `test_validate_tool_registry.py` | Unit | `scripts/validate_tool_registry.py` CLI + exit codes |
| `test_check_file_line_limit.py` | Unit | `scripts/check_file_line_limit.py` incremental scope (explicit file list) |

## Key Dependencies

- `scripts/tool_registry_config.py`
- `tests/architecture/test_tool_registry.py` (CI gate vs `_TOOL_LAYERS`)
- `tests/architecture/test_file_line_limit.py` (CI full-scan gate)
