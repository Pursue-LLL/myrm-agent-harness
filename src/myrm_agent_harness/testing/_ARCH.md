# myrm_agent_harness/testing/

## Overview

Shipped pytest and local-dev teardown helpers consumed by server and harness test suites.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Core | Re-exports `terminate_browser_processes_in_tree` | — |
| `browser_process_cleanup.py` | Core | Terminate automation child processes in a pytest process tree | ✅ |

## Key Dependencies

- `myrm_agent_harness.utils.os_compat::terminate_process_graceful` (POS: Cross-platform process group control.)
- Invoked from `myrm-agent-server/tests/conftest.py` via `pytest_sessionfinish` / `atexit`
- Complements `myrm_agent_harness.toolkits.browser.doctor` global orphan cleanup
