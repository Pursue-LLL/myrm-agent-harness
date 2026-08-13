# tests/support/

## Overview

Pytest-only helpers for harness test teardown and local dev hygiene. Not shipped in the harness wheel.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `browser_process_cleanup.py` | Core | Terminate automation child processes in a pytest process tree | ✅ |
| `sse_shutdown_flag.py` | Core | Reset sse-starlette's process-global shutdown flag between test uvicorn servers | ✅ |
| `test_browser_process_cleanup.py` | Unit | Unit tests for `browser_process_cleanup` (100% line coverage) | — |
| `test_conftest_browser_cleanup_wiring.py` | Integration | conftest hook smoke + harness/server marker parity | — |
| `test_sse_shutdown_flag.py` | Unit | Unit tests for `sse_shutdown_flag` (flag clearing + missing-flag no-op) | — |

## Key Dependencies

- `myrm_agent_harness.utils.os_compat::terminate_process_graceful`
- Invoked from `tests/conftest.py` and `tests/toolkits/browser/conftest.py` via `pytest_sessionfinish` / `atexit`
- Complements `toolkits.browser.doctor` global orphan cleanup
- Mirror copy: `myrm-agent/myrm-agent-server/tests/support/browser_process_cleanup.py` (keep markers in sync)
