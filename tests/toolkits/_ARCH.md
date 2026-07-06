# tests/toolkits/

## Overview

Mirrors `src/myrm_agent_harness/toolkits/<name>/` — one subdirectory per shipped toolkit package.

## Rules

1. **Name parity**: `tests/toolkits/<name>/` must have a matching `src/myrm_agent_harness/toolkits/<name>/` package.
2. **No empty shells**: every subdirectory must contain at least one `test_*.py` (or be deleted). Empty dirs with only `__pycache__` are forbidden.
3. **Root-level tests**: shared toolkit tests may live as `tests/toolkits/test_*.py` beside subdirs (e.g. `test_mcp_timeout.py`).

## Submodule index

| Path | Mirrors | Notes |
|------|---------|-------|
| `browser/` | `toolkits/browser/` | Real Chromium tests need `integration` / `e2e` markers |
| `code_execution/` | `toolkits/code_execution/` | Sandbox / security |
| `mcp/` | `toolkits/mcp/` | MCP client pool |
| `memory/` | `toolkits/memory/` | Memory manager |
| `wiki/` | `toolkits/wiki/` | Wiki pipeline |
| *(other subdirs)* | same-name under `src/.../toolkits/` | See disk listing |

## Gate

`tests/architecture/test_toolkits_test_mirror.py` enforces name parity and non-empty test trees.

## Parent

[tests/_ARCH.md](../_ARCH.md)
