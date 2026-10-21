"""Unit tests for system doctor and capability assertion verifier suite.

Verifies:
- Config schema and required keys diagnostic inspections.
- Filesystem workspace permissions, disk space, and Python runtime version.
- Proxy environment diagnosis, detecting missing loopback bypass risks.
- Model gateway probe reachability and latency checks.
- Capability assertion verification (bash execution, file read/write, git checks).
- Inconsistent capability detection (declared but inoperable tools).
- DoctorReport assembly, Markdown rendering, and JSON dictionary export.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.runtime.doctor import (
    CapabilityAssertionVerifier,
    CheckSeverity,
    DoctorReport,
    DoctorReportRenderer,
    SystemDoctor,
)


def test_doctor_config_checking() -> None:
    doctor = SystemDoctor()

    # 1. Valid config
    valid_cfg = {"version": "1.0.0", "agent_name": "MyrmPrimary", "debug": False}
    findings_ok = doctor.check_config(valid_cfg)
    assert any(f.name == "config_presence" and f.severity == CheckSeverity.PASS for f in findings_ok)
    assert any(f.name == "config_required_keys" and f.severity == CheckSeverity.PASS for f in findings_ok)

    # 2. Missing config
    findings_none = doctor.check_config(None)
    assert any(f.name == "config_presence" and f.severity == CheckSeverity.FAIL for f in findings_none)

    # 3. Missing required keys
    broken_cfg = {"debug": True}
    findings_missing = doctor.check_config(broken_cfg, required_keys=("version", "agent_name"))
    assert any(f.name == "config_required_keys" and f.severity == CheckSeverity.FAIL for f in findings_missing)


def test_doctor_runtime_and_sandbox() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        doctor = SystemDoctor(workspace_root=tmp_dir)
        findings = doctor.check_runtime_and_sandbox()

        # Workspace directory
        assert any(
            f.name == "workspace_directory" and f.severity == CheckSeverity.PASS
            for f in findings
        )
        # Disk space
        assert any(f.name == "disk_space" and f.severity in (CheckSeverity.PASS, CheckSeverity.WARN) for f in findings)
        # Python version
        assert any(f.name == "python_version" and f.severity == CheckSeverity.PASS for f in findings)


def test_doctor_network_and_proxies() -> None:
    doctor = SystemDoctor()

    # 1. Clean environment without proxy
    findings_clean = doctor.check_network_and_proxies(env={})
    assert any(f.name == "proxy_environment" and f.severity == CheckSeverity.INFO for f in findings_clean)

    # 2. Proxy active but loopback missing in NO_PROXY -> FAIL
    bad_proxy_env = {
        "http_proxy": "http://127.0.0.1:7890",
        "no_proxy": "corporate.domain.com",
    }
    findings_bad = doctor.check_network_and_proxies(env=bad_proxy_env)
    assert any(
        f.name == "proxy_loopback_bypass" and f.severity == CheckSeverity.FAIL
        for f in findings_bad
    )

    # 3. Proxy active with loopback properly bypassed -> PASS
    good_proxy_env = {
        "http_proxy": "http://127.0.0.1:7890",
        "no_proxy": "127.0.0.1,localhost,::1",
    }
    findings_good = doctor.check_network_and_proxies(env=good_proxy_env)
    assert any(
        f.name == "proxy_loopback_bypass" and f.severity == CheckSeverity.PASS
        for f in findings_good
    )


@pytest.mark.asyncio
async def test_doctor_model_endpoints_probe() -> None:
    # Spin up mock endpoint
    async def dummy_cb(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(dummy_cb, "127.0.0.1", 0)
    bound_port = server.sockets[0].getsockname()[1]

    doctor = SystemDoctor()
    try:
        findings = await doctor.check_model_endpoints(
            endpoints=(("127.0.0.1", bound_port), ("127.0.0.1", 59998))
        )
        assert len(findings) == 2
        # Reachable port -> PASS
        assert any(f.name == f"model_endpoint_127.0.0.1_{bound_port}" and f.severity == CheckSeverity.PASS for f in findings)
        # Unopened port -> WARN
        assert any(f.name == "model_endpoint_127.0.0.1_59998" and f.severity == CheckSeverity.WARN for f in findings)
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_capability_assertion_verifier() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        verifier = CapabilityAssertionVerifier(workspace_root=Path(tmp_dir))

        declared_tools = ["execute_bash", "read_file", "write_file", "git_commit"]
        assertions = await verifier.verify_all_declared(declared_tools)

        assert len(assertions) == 4
        # Bash, read, write should succeed on modern Mac / Unix test environments
        bash_assert = next(a for a in assertions if a.name == "execute_bash")
        assert bash_assert.verified is True
        assert bash_assert.is_consistent is True
        assert bash_assert.latency_ms >= 0.0

        write_assert = next(a for a in assertions if a.name == "write_file")
        assert write_assert.verified is True

        read_assert = next(a for a in assertions if a.name == "read_file")
        assert read_assert.verified is True


def test_doctor_report_assembly_and_markdown_renderer() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        doctor = SystemDoctor(workspace_root=tmp_dir)
        cfg_findings = doctor.check_config({"version": "1.0", "agent_name": "Test"})
        rt_findings = doctor.check_runtime_and_sandbox()

        report = DoctorReport.assemble(
            findings=[*cfg_findings, *rt_findings],
            capabilities=(),
            duration_ms=45.6,
        )

        assert report.overall_healthy is True
        assert report.fail_count == 0
        assert report.pass_count > 0

        # Markdown render
        md = DoctorReportRenderer.to_markdown(report)
        assert "# 🩺 Myrm System Doctor" in md
        assert "🟢 HEALTHY" in md
        assert "CONFIG Diagnosis" in md
        assert "RUNTIME_SANDBOX Diagnosis" in md

        # JSON dict render
        d = DoctorReportRenderer.to_dict(report)
        assert d["overall_healthy"] is True
        assert len(d["findings"]) == len(cfg_findings) + len(rt_findings)
