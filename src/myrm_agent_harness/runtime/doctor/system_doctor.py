"""Four-dimensional system health diagnosis engine.

Inspects config validity, runtime filesystem and sandbox isolation, network proxy
environment bypass, and model provider endpoint reachability.

[OUTPUT]
- SystemDoctor: Coordinated health diagnostic inspector.

[INPUT]
- __future__
- os
- shutil
- sys
- time
- collections

[OUTPUT]
- SystemDoctor

[POS]
Four-dimensional system health diagnosis engine.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from myrm_agent_harness.core.network import (
    HealthStatus,
    LoopbackProbe,
    ProxyEnvironmentGuard,
)
from myrm_agent_harness.runtime.doctor.doctor_types import (
    CheckFinding,
    CheckSeverity,
    DoctorCategory,
    DoctorReport,
)


class SystemDoctor:
    """Orchestrates comprehensive environment diagnosis across 4 essential dimensions."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root: Path = (
            Path(workspace_root).resolve() if workspace_root else Path.cwd()
        )
        self.loopback_probe: LoopbackProbe = LoopbackProbe(timeout_seconds=2.0)

    def check_config(
        self,
        config: Mapping[str, object] | None,
        required_keys: tuple[str, ...] = ("version", "agent_name"),
    ) -> list[CheckFinding]:
        """Validate agent configuration existence and schema requirements."""
        findings: list[CheckFinding] = []

        if not config:
            findings.append(
                CheckFinding(
                    name="config_presence",
                    category=DoctorCategory.CONFIG,
                    severity=CheckSeverity.FAIL,
                    message="Agent configuration dictionary is empty or missing.",
                    remediation_hint="Provide a valid configuration map or check config YAML files.",
                )
            )
            return findings

        findings.append(
            CheckFinding(
                name="config_presence",
                category=DoctorCategory.CONFIG,
                severity=CheckSeverity.PASS,
                message="Agent configuration loaded successfully.",
            )
        )

        # Check required keys
        missing_keys = [k for k in required_keys if k not in config]
        if missing_keys:
            findings.append(
                CheckFinding(
                    name="config_required_keys",
                    category=DoctorCategory.CONFIG,
                    severity=CheckSeverity.FAIL,
                    message=f"Configuration is missing required keys: {missing_keys}",
                    remediation_hint=f"Define {missing_keys} in agent config file.",
                )
            )
        else:
            findings.append(
                CheckFinding(
                    name="config_required_keys",
                    category=DoctorCategory.CONFIG,
                    severity=CheckSeverity.PASS,
                    message="All required configuration keys are present.",
                )
            )

        return findings

    def check_runtime_and_sandbox(self) -> list[CheckFinding]:
        """Verify local filesystem permissions, workspace structure, and Python environment."""
        findings: list[CheckFinding] = []

        # 1. Workspace directory existence and writability
        if not self.workspace_root.is_dir():
            findings.append(
                CheckFinding(
                    name="workspace_directory",
                    category=DoctorCategory.RUNTIME_SANDBOX,
                    severity=CheckSeverity.FAIL,
                    message=f"Workspace path does not exist: {self.workspace_root}",
                    remediation_hint=f"Create workspace directory: mkdir -p {self.workspace_root}",
                    is_auto_fixable=True,
                )
            )
        else:
            can_write = os.access(self.workspace_root, os.W_OK)
            findings.append(
                CheckFinding(
                    name="workspace_directory",
                    category=DoctorCategory.RUNTIME_SANDBOX,
                    severity=CheckSeverity.PASS if can_write else CheckSeverity.FAIL,
                    message=f"Workspace path writable: {can_write}",
                    detail=str(self.workspace_root),
                    remediation_hint="Fix folder permissions: chmod +w <path>" if not can_write else "",
                )
            )

        # 2. Disk space check
        _total, _used, free = shutil.disk_usage(self.workspace_root)
        free_mb = free / (1024 * 1024)
        if free_mb < 500:
            findings.append(
                CheckFinding(
                    name="disk_space",
                    category=DoctorCategory.RUNTIME_SANDBOX,
                    severity=CheckSeverity.WARN,
                    message=f"Low disk space remaining: {free_mb:.1f} MB (< 500 MB)",
                    remediation_hint="Clean up temporary build artifacts or expand disk volume.",
                )
            )
        else:
            findings.append(
                CheckFinding(
                    name="disk_space",
                    category=DoctorCategory.RUNTIME_SANDBOX,
                    severity=CheckSeverity.PASS,
                    message=f"Sufficient disk space available: {free_mb:.1f} MB",
                )
            )

        # 3. Python runtime version (>= 3.11 required)
        py_version = sys.version_info
        if py_version < (3, 11):
            findings.append(
                CheckFinding(
                    name="python_version",
                    category=DoctorCategory.RUNTIME_SANDBOX,
                    severity=CheckSeverity.FAIL,
                    message=f"Python version {py_version.major}.{py_version.minor} is below minimum 3.11",
                    remediation_hint="Upgrade Python interpreter to 3.11 or higher.",
                )
            )
        else:
            findings.append(
                CheckFinding(
                    name="python_version",
                    category=DoctorCategory.RUNTIME_SANDBOX,
                    severity=CheckSeverity.PASS,
                    message=f"Python version compatible: {py_version.major}.{py_version.minor}.{py_version.micro}",
                )
            )

        return findings

    def check_network_and_proxies(
        self,
        env: Mapping[str, str] | None = None,
    ) -> list[CheckFinding]:
        """Verify system proxy configuration and ensure proper loopback bypass."""
        findings: list[CheckFinding] = []
        snapshot = ProxyEnvironmentGuard.capture_snapshot(env)

        if not snapshot.has_any_proxy_configured:
            findings.append(
                CheckFinding(
                    name="proxy_environment",
                    category=DoctorCategory.NETWORK_EGRESS,
                    severity=CheckSeverity.INFO,
                    message="No system proxy configured; traffic routes directly.",
                )
            )
            return findings

        # Proxy is configured -> Check NO_PROXY loopback coverage
        if snapshot.covers_standard_loopback:
            findings.append(
                CheckFinding(
                    name="proxy_loopback_bypass",
                    category=DoctorCategory.NETWORK_EGRESS,
                    severity=CheckSeverity.PASS,
                    message="System proxy active with valid NO_PROXY loopback bypass.",
                    detail=f"NO_PROXY: {snapshot.no_proxy}",
                )
            )
        else:
            findings.append(
                CheckFinding(
                    name="proxy_loopback_bypass",
                    category=DoctorCategory.NETWORK_EGRESS,
                    severity=CheckSeverity.FAIL,
                    message="System proxy configured but missing 127.0.0.1/localhost in NO_PROXY.",
                    detail="Causes loopback deadlocks and connection errors with local gateways.",
                    remediation_hint="Export NO_PROXY='127.0.0.1,localhost,::1,127.0.0.0/8' or call ProxyEnvironmentGuard.enforce_loopback_bypass().",
                    is_auto_fixable=True,
                )
            )

        return findings

    async def check_model_endpoints(
        self,
        endpoints: tuple[tuple[str, int], ...] = (("127.0.0.1", 8317),),
    ) -> list[CheckFinding]:
        """Probe configured model gateway / local proxy endpoints."""
        findings: list[CheckFinding] = []

        for host, port in endpoints:
            probe_res = await self.loopback_probe.probe_tcp_port(host, port)
            if probe_res.status == HealthStatus.HEALTHY:
                findings.append(
                    CheckFinding(
                        name=f"model_endpoint_{host}_{port}",
                        category=DoctorCategory.MODEL,
                        severity=CheckSeverity.PASS,
                        message=f"Model gateway reachable at {host}:{port} ({probe_res.latency_ms:.1f}ms)",
                    )
                )
            elif probe_res.status == HealthStatus.INTERCEPTED:
                findings.append(
                    CheckFinding(
                        name=f"model_endpoint_{host}_{port}",
                        category=DoctorCategory.MODEL,
                        severity=CheckSeverity.FAIL,
                        message=f"Model gateway at {host}:{port} intercepted by system proxy!",
                        remediation_hint="Apply Surge/Clash bypass rule or inject direct transport kwargs.",
                    )
                )
            else:
                findings.append(
                    CheckFinding(
                        name=f"model_endpoint_{host}_{port}",
                        category=DoctorCategory.MODEL,
                        severity=CheckSeverity.WARN,
                        message=f"Model gateway not listening on {host}:{port} ({probe_res.error_message})",
                        remediation_hint=f"Ensure local LLM server or proxy is running on port {port}.",
                    )
                )

        return findings

    async def run_full_diagnosis(
        self,
        config: Mapping[str, object] | None = None,
        model_endpoints: tuple[tuple[str, int], ...] = (("127.0.0.1", 8317),),
    ) -> DoctorReport:
        """Run all four diagnostic phases and assemble a comprehensive report."""
        start_ts = time.perf_counter()
        all_findings: list[CheckFinding] = []

        all_findings.extend(self.check_config(config))
        all_findings.extend(self.check_runtime_and_sandbox())
        all_findings.extend(self.check_network_and_proxies())
        model_findings = await self.check_model_endpoints(model_endpoints)
        all_findings.extend(model_findings)

        duration_ms = (time.perf_counter() - start_ts) * 1000.0
        return DoctorReport.assemble(
            findings=all_findings,
            capabilities=(),
            duration_ms=duration_ms,
        )
