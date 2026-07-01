# tests/support/

## Overview

Pytest-only helpers for harness test teardown and local dev hygiene. Not shipped in the harness wheel.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `browser_process_cleanup.py` | Core | Terminate automation child processes in a pytest process tree | ✅ |
| `test_browser_process_cleanup.py` | Unit | Unit tests for `browser_process_cleanup` (100% line coverage) | — |

## Key Dependencies

- `myrm_agent_harness.utils.os_compat::terminate_process_graceful`
- Invoked from `tests/conftest.py` and `tests/toolkits/browser/conftest.py` via `pytest_sessionfinish` / `atexit`
- Complements `toolkits.browser.doctor` global orphan cleanup
- Mirror copy: `myrm-agent/myrm-agent-server/tests/support/browser_process_cleanup.py` (keep markers in sync)
