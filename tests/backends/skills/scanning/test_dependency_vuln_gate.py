"""Unit tests for check_workspace_dependency_vulns CI gate."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci.check_workspace_dependency_vulns import (
    VulnFindingItem,
    evaluate_gate_results,
    format_report_json,
    format_report_markdown,
    load_ignored_advisories,
)

from myrm_agent_harness.backends.skills.scanning.scanner import ScanSeverity


def test_load_ignored_advisories(tmp_path: Path) -> None:
    cfg = tmp_path / "vuln_config.json"
    cfg.write_text(
        json.dumps(
            {
                "ignored_vulnerabilities": ["GHSA-1234-5678", "cve-2024-9999"],
            }
        ),
        encoding="utf-8",
    )
    ignored = load_ignored_advisories(cfg)
    assert "GHSA-1234-5678" in ignored
    assert "CVE-2024-9999" in ignored


def test_evaluate_gate_results_clean() -> None:
    findings: list[VulnFindingItem] = []
    passed, violations, warnings = evaluate_gate_results(findings, fail_on=ScanSeverity.HIGH)
    assert passed is True
    assert len(violations) == 0
    assert len(warnings) == 0


def test_evaluate_gate_results_blocking_high() -> None:
    findings = [
        VulnFindingItem(
            workspace="myrm-agent-server",
            package_name="test-vuln-pkg",
            version="1.0.0",
            ecosystem="PyPI",
            source_file="uv.lock",
            advisory_id="GHSA-HIGH-001",
            severity=ScanSeverity.HIGH,
            summary="High severity vulnerability",
            fixed_version="1.0.1",
        ),
        VulnFindingItem(
            workspace="myrm-agent-frontend",
            package_name="test-low-pkg",
            version="2.0.0",
            ecosystem="npm",
            source_file="bun.lock",
            advisory_id="GHSA-LOW-002",
            severity=ScanSeverity.LOW,
            summary="Low severity warning",
            fixed_version="2.0.1",
        ),
    ]

    passed, violations, warnings = evaluate_gate_results(findings, fail_on=ScanSeverity.HIGH)
    assert passed is False
    assert len(violations) == 1
    assert violations[0].advisory_id == "GHSA-HIGH-001"
    assert len(warnings) == 1
    assert warnings[0].advisory_id == "GHSA-LOW-002"


def test_evaluate_gate_results_critical_only() -> None:
    findings = [
        VulnFindingItem(
            workspace="myrm-agent-server",
            package_name="test-vuln-pkg",
            version="1.0.0",
            ecosystem="PyPI",
            source_file="uv.lock",
            advisory_id="GHSA-HIGH-001",
            severity=ScanSeverity.HIGH,
            summary="High severity vulnerability",
            fixed_version="1.0.1",
        ),
    ]

    # When fail_on is CRITICAL, HIGH findings should be treated as warnings, gate passes
    passed, violations, warnings = evaluate_gate_results(findings, fail_on=ScanSeverity.CRITICAL)
    assert passed is True
    assert len(violations) == 0
    assert len(warnings) == 1


def test_format_report_json_and_markdown() -> None:
    findings = [
        VulnFindingItem(
            workspace="myrm-agent-server",
            package_name="test-vuln-pkg",
            version="1.0.0",
            ecosystem="PyPI",
            source_file="uv.lock",
            advisory_id="GHSA-HIGH-001",
            severity=ScanSeverity.HIGH,
            summary="High severity vulnerability",
            fixed_version="1.0.1",
        ),
    ]

    passed, violations, warnings = evaluate_gate_results(findings, fail_on=ScanSeverity.HIGH)
    report_json_str = format_report_json(
        passed=passed,
        fail_on=ScanSeverity.HIGH,
        total_dependencies=10,
        violations=violations,
        warnings=warnings,
    )
    data = json.loads(report_json_str)
    assert data["passed"] is False
    assert data["fail_on_severity"] == "HIGH"
    assert data["violation_count"] == 1
    assert data["violations"][0]["advisory_id"] == "GHSA-HIGH-001"

    report_md_str = format_report_markdown(
        passed=passed,
        fail_on=ScanSeverity.HIGH,
        total_dependencies=10,
        violations=violations,
        warnings=warnings,
    )
    assert "Supply Chain Dependency Vulnerability Gate: ❌ BLOCKED" in report_md_str
    assert "GHSA-HIGH-001" in report_md_str
    assert "test-vuln-pkg" in report_md_str

