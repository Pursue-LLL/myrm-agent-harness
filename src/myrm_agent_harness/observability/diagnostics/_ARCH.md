# observability/diagnostics/

## Overview
Framework-level self-inspection and health-check protocol. Supports structured issue metadata (measured/expected/cause) and sensitive information redaction for API responses.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Unified diagnostic protocol entry point with probe auto-registration. | ✅ |
| manager.py | Core | Provides register_diagnostic, register_protocol, run_all_diagnostics. | ✅ |
| performance.py | Core | Provides register_benchmark, run_all_benchmarks for heavy performance testing. | ✅ |
| probes.py | Core | Health diagnostic probes: Network, WorkspaceStorage (incl. ripgrep warn), Database, Qdrant, Tokenizer, HookSystem, DesktopControl (OS Accessibility/Screen Recording via `check_permissions`; WARN `meta_data.settings_deeplinks`). Server wiring: `test_doctor.py::test_desktop_control_probe_in_doctor`; permissions API session close: `tests/api/webui/test_desktop_permissions.py`; WARN deeplink meta: `tests/observability/test_probes.py::TestCheckDesktopPermissionsHealth::test_local_missing_permissions_warns`. | ✅ |
| system_resources.py | Core | Host-level resource probe `check_system_resources`: CPU / memory / PID utilization. Reads cgroup v1/v2 pids counters (`pids.current` / `pids.max`) with psutil fallback for local single-machine deployments; PID warn >70% / fail >=90% with browser process attribution. | ✅ |
| system_exhaustion.py | Core | Host-level system resource exhaustion probe `check_system_exhaustion`: Swap / Pagefile pressure, Linux CommitLimit saturation, and system/process file descriptor (FD / Handle) leaks. | ✅ |
| process_tree.py | Core | Process tree PPID lineage inspector (`inspect_process_lineage`), leaked orphan worker detection (`detect_orphan_processes`), and structured causal diagnostic reporting (`diagnose_process_tree_health`). | ✅ |
| supply_chain.py | Core | Runtime dependency and supply chain security probe `check_supply_chain_health` (installed package scanning against offline advisories and OSV.dev). | ✅ |
| benchmark_probes.py | Core | Provides performance benchmark probes for LLM, Embedding, and Search. | ✅ |
| protocols.py | Core | Provides HealthReport (with measured/expected/cause fields), DiagnosticProtocol, redact_health_report. | ✅ |
| migration_reporter.py | Core | Migration progress tracking protocol, progress events, and malformed record diagnostic reporter. | ✅ |
| gateway_health.py | Core | Gateway runtime vitals probe (event loop lag, process RSS, asyncio task count), zero-payload redacted health DTO, and OTLP posture detection. Registered into `/health/doctor`. | ✅ |

## Key Dependencies

- `toolkits` (via probes — vector, retriever, web_search, llms)
