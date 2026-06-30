# tests/support/

## Overview

Pytest-only helpers for teardown and local dev hygiene. Browser process cleanup delegates to the shipped `myrm_agent_harness.testing` module.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Re-export | Re-exports `myrm_agent_harness.testing.browser_process_cleanup.terminate_browser_processes_in_tree` | ✅ |

## Key Dependencies

- `myrm_agent_harness.testing.browser_process_cleanup` (POS: Shipped pytest teardown helper for downstream test suites.)
- Invoked from `tests/conftest.py` via `pytest_sessionfinish` / `atexit`
- Browser tests: `tests/toolkits/browser/conftest.py` via `atexit`
