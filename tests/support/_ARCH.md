# tests/support/

## Overview

Pytest-only helpers for harness test teardown, local dev hygiene, and live MCP transport tests. Not shipped in the harness wheel.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `browser_process_cleanup.py` | Core | Terminate automation child processes in a pytest process tree | ✅ |
| `sse_shutdown_flag.py` | Core | Reset sse-starlette's process-global shutdown flag between test uvicorn servers | ✅ |
| `mcp_live_server.py` | Core | Real uvicorn-hosted MCP servers (SSE / streamable HTTP, optionally TLS or mTLS) on pre-bound loopback ports, exposing echo/add tools and optional `initialize` instructions; single bootstrap shared by every live transport test | ✅ |
| `mcp_tls_pki.py` | Core | Throwaway PKI (private CA, rogue CA, server leaf, plain and passphrase-encrypted client leaf) whose chains satisfy Python 3.13 strict X.509 verification, plus the TLS-rejection error-text markers | ✅ |
| `mcp_launch_gates.py` | Core | Patch targets and `RecordingTrustGate` for the stdio launch gates (workspace trust + OSV malware check) shared by actor and enumeration tests | ✅ |
| `test_browser_process_cleanup.py` | Unit | Unit tests for `browser_process_cleanup` (100% line coverage) | — |
| `test_conftest_browser_cleanup_wiring.py` | Integration | conftest hook smoke + harness/server marker parity | — |
| `test_sse_shutdown_flag.py` | Unit | Unit tests for `sse_shutdown_flag` (flag clearing + missing-flag no-op) | — |

## Key Dependencies

- `myrm_agent_harness.utils.os_compat::terminate_process_graceful`
- Invoked from `tests/conftest.py` and `tests/toolkits/browser/conftest.py` via `pytest_sessionfinish` / `atexit`
- Complements the stamp-based `toolkits.browser.doctor` orphan check (this helper reaps by process tree instead)
- Mirror copy: `myrm-agent/myrm-agent-server/tests/support/browser_process_cleanup.py` (keep markers in sync)
