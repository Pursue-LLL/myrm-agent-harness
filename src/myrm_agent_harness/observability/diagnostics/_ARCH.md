# observability/diagnostics/

## Overview
Framework-level self-inspection and health-check protocol. Supports structured issue metadata (measured/expected/cause) and sensitive information redaction for API responses.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Unified diagnostic protocol entry point with probe auto-registration. | ✅ |
| manager.py | Core | Provides register_diagnostic, register_protocol, run_all_diagnostics; every hook runs under `DIAGNOSTIC_HOOK_TIMEOUT_S`, and a timeout or crash becomes a `fail` report with neutral wording (no deadlock claim, no restart advice). | ✅ |
| performance.py | Core | Benchmark hook registry (`register_benchmark`, `run_all_benchmarks`): hosts register async probes against targets only they can resolve (LLM, embedding, search provider); timeouts and crashes become `fail` reports. The framework registers no hooks of its own. | ✅ |
| probes.py | Core | Health diagnostic probes registered in probe order: Network (staggered first-win race over fallback URLs; a blocked endpoint cannot hide a working connection, and the probe's own budget stays below the hook limit), WorkspaceStorage (incl. ripgrep warn), Database, Qdrant (defined in `vector_probe.py`), Tokenizer, HookSystem, DesktopControl (defined in `desktop_probe.py`), TraceExportAudit. Server wiring: `test_doctor.py::test_desktop_control_probe_in_doctor`. | ✅ |
| desktop_probe.py | Core | Doctor `DesktopControl` probe `check_desktop_permissions_health` (registered through `probes.py`): OS grants + capturable via `check_permissions(probe_capture=True)`; PASS only when `PermissionStatus.capture_ready`; WARN `WARN_DESKTOP_CAPTURE_NOT_READY` / missing; deeplink meta; a cloud sandbox reports its visual-desktop (VNC) entitlement instead of local grants. Permissions API: `tests/api/webui/test_desktop_permissions.py`; desktop health: `tests/observability/test_probes.py::TestCheckDesktopPermissionsHealth`. | ✅ |
| vector_probe.py | Core | Doctor `VectorDB` probe `check_qdrant_health` (registered through `probes.py`): FAIL `ERR_VECTOR_STORE_ON_MEMORY_FALLBACK` (the WebUI doctor shows its localized message) while an embedded Qdrant store runs on the in-memory fallback (`embedded_fallback_paths()`), otherwise verifies the Qdrant library can initialize a throwaway in-memory store. User-facing wording names no backend and carries no raw exception (the exception goes to the log). | ✅ |
| system_resources.py | Core | Host-level resource probe `check_system_resources`: CPU / memory / PID utilization. Reads cgroup v1/v2 pids counters (`pids.current` / `pids.max`) with psutil fallback for local single-machine deployments; PID warn >70% / fail >=90% with browser process attribution. | ✅ |
| system_exhaustion.py | Core | Host-level system resource exhaustion probe `check_system_exhaustion`: Swap / Pagefile pressure, Linux CommitLimit saturation, and system/process file descriptor (FD / Handle) leaks. A nearly full swap fails only while available physical memory is also under 10% (macOS sizes swap on demand, so full swap alone is a warning); typed snapshot `SystemExhaustionSnapshot`. | ✅ |
| supply_chain.py | Core | Runtime dependency and supply chain security probe `check_supply_chain_health` (installed package scanning against offline advisories and OSV.dev). | ✅ |
| protocols.py | Core | Provides HealthReport (with measured/expected/cause fields), DiagnosticProtocol, redact_health_report. | ✅ |
| gateway_health.py | Core | Gateway runtime vitals probe (event loop lag, process RSS, asyncio task count), zero-payload redacted health DTO, and OTLP posture detection. Registered into `/health/doctor`. | ✅ |

## Key Dependencies

- `toolkits` (via probes — vector, retriever, web_search, llms)
