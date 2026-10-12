# tests/scripts/

## Overview

Unit tests for `scripts/` maintenance tooling (tool registry engine/models/config/validator, turn1 token inventory, file line-limit gate, module-reachability and import-resolvability gates). Architecture gate tests for the same scripts live under `tests/architecture/`.

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
| `test_check_test_source_assertions.py` | Unit | `scripts/check_test_source_assertions.py` AST scanners (source-text assertion detection, non-Python and structural reads ignored, unparsable input) |
| `test_check_module_coverage.py` | Unit | `scripts/check_module_coverage.py` floor CLI (below/at floor, unmeasured module, missing data file) |
| `test_module_reachability_engine.py` | Unit | `scripts/module_reachability_engine.py` evidence rules on synthetic packages (facade re-exports/aliases not uses, hub bindings and lazy tables, name collisions ignored, dead-unit chains, roots: `__main__`/entry points/server tree/public surface) |
| `test_check_module_reachability.py` | Unit | `scripts/check_module_reachability.py` CLI (exit codes 0/1/2/3, empty scan fails, missing server tree reported as not evaluated, `--incremental`, `--json`, entry-point discovery) |
| `test_import_resolvability_engine.py` | Unit | `scripts/import_resolvability_engine.py` on synthetic packages (module existence, relative imports, lazy / `try` / `TYPE_CHECKING` imports, import-time name binding, `__all__`, star re-exports and cycles, dynamic namespaces, unparsable files, cross-root scan scope, ordering, bytecode dirs) |
| `test_check_import_resolvability.py` | Unit | `scripts/check_import_resolvability.py` CLI (exit codes 0/1/2, `--json`, `--package` / `--scan` validation and server-tree scan, `--incremental` scope and `harness_sources_changed`) |

## Key Dependencies

- `scripts/tool_registry_config.py`
- `tests/architecture/test_tool_registry.py` (CI gate vs `_TOOL_LAYERS`)
- `tests/architecture/test_file_line_limit.py` (CI full-scan gate)
