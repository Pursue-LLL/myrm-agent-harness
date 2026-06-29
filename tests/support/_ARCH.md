# tests/support/

## Overview
Pytest-only helpers for teardown and local dev hygiene. Not part of the distributable package.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `browser_process_cleanup.py` | Core | Gracefully terminate automation child processes in the pytest process tree via `os_compat.terminate_process_graceful`. | ✅ |

## Key Dependencies

- `ps` subprocess (stdlib) for process-tree scans
- `myrm_agent_harness.utils.os_compat.terminate_process_graceful` for teardown kills
- Invoked from `tests/conftest.py` via `pytest_sessionfinish` / `atexit`
- Browser tests: `tests/toolkits/browser/conftest.py` via `atexit`
