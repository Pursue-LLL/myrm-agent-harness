"""Unit tests for Agent Egress Telemetry Scraper & Enterprise DLP Guard Suite (Item 39).

[INPUT]
- TelemetrySignatureRegistry and EgressSecurityPolicyValidator.

[OUTPUT]
- Verified test outcomes ensuring secret telemetry endpoints, tracking SDKs,
  homoglyph evasions, and CIDR bypass attempts are strictly rejected.

[POS]
- Harness core security test suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.core.security.egress_dlp import (
    DLPVerdict,
    EgressRule,
    EgressSecurityPolicyValidator,
    TelemetryEgressBlockedError,
    TelemetrySignatureRegistry,
)


def test_registry_normalization_and_evasion_detection() -> None:
    # 1. Normal clean host
    host1, err1 = TelemetrySignatureRegistry.normalize_host("https://api.crewai.com:443/v1/telemetry")
    assert host1 == "api.crewai.com"
    assert err1 is None

    # 2. Wildcard domain
    host2, err2 = TelemetrySignatureRegistry.normalize_host("*.posthog.com.")
    assert host2 == "posthog.com"
    assert err2 is None

    # 3. Homoglyph evasion (non-ASCII char)
    _host3, err3 = TelemetrySignatureRegistry.normalize_host("posthоg.com")  # Cyrillic 'о'
    assert err3 == DLPVerdict.BLOCKED_HOMOGLYPH_EVASION

    # 4. CIDR bypass
    _host4, err4 = TelemetrySignatureRegistry.normalize_host("10.0.0.0/16")
    assert err4 == DLPVerdict.BLOCKED_CIDR_BYPASS


def test_validator_egress_rules_blocking_and_exceptions() -> None:
    validator = EgressSecurityPolicyValidator()

    # Safe rules
    safe_rules = [
        EgressRule(destination="api.openai.com", port=443),
        EgressRule(destination="github.com", port=443),
    ]
    safe_res = validator.validate_egress_rules(safe_rules)
    assert safe_res.is_safe is True
    assert safe_res.verdict == DLPVerdict.ALLOWED

    # Blocked telemetry rules
    bad_rules = [
        EgressRule(destination="api.openai.com", port=443),
        EgressRule(destination="telemetry.crewai.com", port=443),
    ]
    blocked_res = validator.validate_egress_rules(bad_rules)
    assert blocked_res.is_safe is False
    assert blocked_res.verdict == DLPVerdict.BLOCKED_TELEMETRY_DOMAIN
    assert len(blocked_res.offending_rules) == 1
    assert "CrewAI" in blocked_res.audit_trail

    # Allowed exception bypass
    exception_res = validator.validate_egress_rules(
        bad_rules, allowed_exceptions={"telemetry.crewai.com"}
    )
    assert exception_res.is_safe is True

    # assert_compliant raises
    with pytest.raises(TelemetryEgressBlockedError):
        validator.assert_compliant(bad_rules)


def test_validator_scan_dependencies() -> None:
    validator = EgressSecurityPolicyValidator()

    # Clean requirements
    clean_manifest = "fastapi>=0.100.0\npydantic>=2.0\nrequests>=2.30.0\n"
    res_clean = validator.scan_dependencies(clean_manifest)
    assert res_clean.is_safe is True

    # Telemetry requirements
    dirty_manifest = "fastapi>=0.100.0\nposthog>=3.0.0\nsentry-sdk[fastapi]>=1.40.0\n"
    res_dirty = validator.scan_dependencies(dirty_manifest)
    assert res_dirty.is_safe is False
    assert res_dirty.verdict == DLPVerdict.BLOCKED_TELEMETRY_DEPENDENCY
    assert "posthog" in res_dirty.detected_dependencies
    assert "sentry-sdk[fastapi]" in res_dirty.detected_dependencies


def test_validator_scan_codebase_project(tmp_path: Path) -> None:
    validator = EgressSecurityPolicyValidator()

    proj_dir = tmp_path / "agent_project"
    proj_dir.mkdir()

    # 1. Clean project
    code_file = proj_dir / "main.py"
    code_file.write_text("print('hello AI')", encoding="utf-8")
    assert validator.scan_codebase_telemetry(proj_dir).is_safe is True

    # 2. Add telemetry endpoint in code
    code_file.write_text(
        "import urllib.request\nENDPOINT = 'https://telemetry.crewai.com/track'\n",
        encoding="utf-8",
    )
    res_code = validator.scan_codebase_telemetry(proj_dir)
    assert res_code.is_safe is False
    assert res_code.verdict == DLPVerdict.BLOCKED_TELEMETRY_DOMAIN
    assert "crewai.com" in res_code.audit_trail
