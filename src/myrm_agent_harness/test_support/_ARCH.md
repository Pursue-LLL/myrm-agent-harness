# test_support/

## Overview
Pytest-only helpers shipped with harness for teardown and local dev hygiene (not consumer API).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `browser_process_cleanup.py` | Core | Gracefully terminate automation child processes in the pytest process tree via `os_compat.terminate_process_graceful`. | ✅ |

## Key Dependencies

- `ps` subprocess (stdlib) for process-tree scans
- `utils.os_compat.terminate_process_graceful` for teardown kills
- Invoked from `tests/conftest.py` via `pytest_sessionfinish` / `atexit`
- Maintainer script tests: `tests/dev/test_run_pytest_safe.py`
