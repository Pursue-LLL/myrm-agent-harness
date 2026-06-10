# testing/

## Overview
Test-only helpers shipped with harness for pytest teardown and local dev hygiene.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `browser_process_cleanup.py` | Core | Terminate automation child processes in the current pytest process tree (Chromium headless, puppeteer, patchright/playwright driver nodes). | ✅ |

## Key Dependencies

- `ps` subprocess (stdlib) for process-tree scans
- Invoked from `tests/conftest.py` via `pytest_sessionfinish` / `atexit`
