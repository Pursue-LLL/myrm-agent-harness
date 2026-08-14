# tests/scripts/

## Overview

Unit tests for `scripts/` maintenance tooling (tool registry engine/models/config/validator, turn1 token inventory, file line-limit gate). Architecture gate tests for the same scripts live under `tests/architecture/`.

## File Index

| File | Role | Description |
|------|------|-------------|
| `test_tool_registry_engine.py` | Unit | `scripts/tool_registry_engine.py` scan behavior |
| `test_tool_registry_config.py` | Unit | `scripts/tool_registry_config.py` SSOT-derived registry config (product_id/layer/description) |
| `test_measure_turn1_token_inventory.py` | Unit | `scripts/measure_turn1_token_inventory.py` pure helpers + stubbed tool list (no heavy backends in CI) |
| `test_tool_registry_models.py` | Unit | `scripts/tool_registry_models.py` DTO validation |
| `test_validate_tool_registry.py` | Unit | `scripts/validate_tool_registry.py` CLI + exit codes |
| `test_check_file_line_limit.py` | Unit | `scripts/check_file_line_limit.py` incremental scope (explicit file list) |
| `test_boundary_engine.py` | Unit | `scripts/boundary_engine.py` core detection (git-change discovery, static/dynamic import collection, banned/priority classification, fix) |

## Key Dependencies

- `scripts/tool_registry_config.py`
- `tests/architecture/test_tool_registry.py` (CI gate vs `_TOOL_LAYERS`)
- `tests/architecture/test_file_line_limit.py` (CI full-scan gate)
