# observability/diagnostics/

## Overview
Framework-level self-inspection and health-check protocol. Supports structured issue metadata (measured/expected/cause) and sensitive information redaction for API responses.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Unified diagnostic protocol entry point with probe auto-registration. | ✅ |
| manager.py | Core | Provides register_diagnostic, register_protocol, run_all_diagnostics. | ✅ |
| performance.py | Core | Provides register_benchmark, run_all_benchmarks for heavy performance testing. | ✅ |
| probes.py | Core | Health diagnostic probes: Network, WorkspaceStorage (incl. ripgrep warn), Database, Qdrant, SystemResources (non-blocking CPU sample via `asyncio.to_thread`), Tokenizer, HookSystem, DesktopControl (OS Accessibility/Screen Recording via `check_permissions`). Server wiring: `test_doctor.py::test_desktop_control_probe_in_doctor`; permissions API session close: `tests/api/webui/test_desktop_permissions.py`. | ✅ |
| benchmark_probes.py | Core | Provides performance benchmark probes for LLM, Embedding, and Search. | ✅ |
| protocols.py | Core | Provides HealthReport (with measured/expected/cause fields), DiagnosticProtocol, redact_health_report. | ✅ |

## Key Dependencies

- `toolkits` (via probes — vector, retriever, web_search, llms)
