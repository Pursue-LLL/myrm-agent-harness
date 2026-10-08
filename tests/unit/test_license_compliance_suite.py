"""Unit test suite for ThirdPartyAssetLicenseComplianceAndCopyleftGatingSuite (Item 37).

[INPUT]
- SpdxLicenseRegistry, LicenseComplianceGate, and LicenseInventoryLedger.

[OUTPUT]
- Verified test outcomes ensuring robust SPDX normalization, copyleft gating,
  and deployment-aware risk classification across local desktop and cloud commercial tiers.

[POS]
- Harness core security test suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.core.security.license_compliance import (
    AssetLicenseDescriptor,
    CopyleftBlockedError,
    DeploymentEnvironment,
    LicenseComplianceGate,
    LicenseGateDecision,
    LicenseInventoryLedger,
    LicenseRiskTier,
    SpdxLicenseRegistry,
    UnknownLicenseBlockedError,
)


def test_spdx_registry_normalization() -> None:
    # Permissive standard & aliases
    mit = SpdxLicenseRegistry.normalize("MIT")
    assert mit.spdx_id == "MIT"
    assert mit.risk_tier == LicenseRiskTier.PERMISSIVE
    assert mit.commercial_friendly is True
    assert mit.is_copyleft is False

    apache = SpdxLicenseRegistry.normalize("Apache 2.0")
    assert apache.spdx_id == "Apache-2.0"
    assert apache.risk_tier == LicenseRiskTier.PERMISSIVE

    # Weak copyleft
    mpl = SpdxLicenseRegistry.normalize("MPL-2.0")
    assert mpl.risk_tier == LicenseRiskTier.WEAK_COPYLEFT
    assert mpl.is_copyleft is True

    # Strong copyleft
    agpl = SpdxLicenseRegistry.normalize("AGPL-3.0")
    assert agpl.risk_tier == LicenseRiskTier.STRONG_COPYLEFT
    assert agpl.is_copyleft is True
    assert agpl.commercial_friendly is False

    # Proprietary & Unknown
    prop = SpdxLicenseRegistry.normalize("Commercial Enterprise Edition")
    assert prop.risk_tier == LicenseRiskTier.PROPRIETARY

    unk = SpdxLicenseRegistry.normalize("Custom-In-House-Nonstandard")
    assert unk.risk_tier == LicenseRiskTier.UNKNOWN
    assert unk.spdx_id == "UNKNOWN"

    none_meta = SpdxLicenseRegistry.normalize(None)
    assert none_meta.risk_tier == LicenseRiskTier.UNKNOWN


def test_compliance_gate_local_desktop_evaluations() -> None:
    gate = LicenseComplianceGate(default_environment=DeploymentEnvironment.LOCAL_DESKTOP)

    # Permissive asset
    permissive_asset = AssetLicenseDescriptor(
        asset_id="skill-markdown-tool",
        asset_type="skill",
        detected_license=SpdxLicenseRegistry.normalize("MIT"),
    )
    verdict = gate.evaluate(permissive_asset)
    assert verdict.decision == LicenseGateDecision.ALLOWED

    # Strong copyleft asset in local desktop should warn but not block
    agpl_asset = AssetLicenseDescriptor(
        asset_id="skill-pi-memory",
        asset_type="skill",
        detected_license=SpdxLicenseRegistry.normalize("AGPL-3.0"),
    )
    verdict_agpl = gate.evaluate(agpl_asset)
    assert verdict_agpl.decision == LicenseGateDecision.WARNING_PROCEED
    # assert_admissible does not raise in local desktop
    gate.assert_admissible(agpl_asset)


def test_compliance_gate_cloud_commercial_blocking_and_overrides() -> None:
    gate = LicenseComplianceGate()
    env = DeploymentEnvironment.CLOUD_COMMERCIAL

    # Strong copyleft in cloud is blocked
    gpl_asset = AssetLicenseDescriptor(
        asset_id="skill-gpl-helper",
        asset_type="skill",
        detected_license=SpdxLicenseRegistry.normalize("GPL-3.0"),
    )
    blocked_verdict = gate.evaluate(gpl_asset, environment=env)
    assert blocked_verdict.decision == LicenseGateDecision.BLOCKED_COPYLEFT_RESTRICTION
    assert blocked_verdict.can_override is True

    with pytest.raises(CopyleftBlockedError):
        gate.assert_admissible(gpl_asset, environment=env)

    # Admin override allows proceeding with warning
    override_verdict = gate.evaluate(gpl_asset, environment=env, allow_override=True)
    assert override_verdict.decision == LicenseGateDecision.WARNING_PROCEED
    assert "ADMIN_OVERRIDE_GRANTED" in override_verdict.audit_notes
    # assert_admissible succeeds with override
    gate.assert_admissible(gpl_asset, environment=env, allow_override=True)

    # Unknown license blocked in cloud
    unknown_asset = AssetLicenseDescriptor(
        asset_id="mcp-mystery-connector",
        asset_type="mcp_server",
        detected_license=SpdxLicenseRegistry.normalize("Mystery-1.0"),
    )
    unk_verdict = gate.evaluate(unknown_asset, environment=env)
    assert unk_verdict.decision == LicenseGateDecision.BLOCKED_UNKNOWN_LICENSE

    with pytest.raises(UnknownLicenseBlockedError):
        gate.assert_admissible(unknown_asset, environment=env)


def test_license_inventory_ledger_and_sbom_export(tmp_path: Path) -> None:
    ledger = LicenseInventoryLedger()

    # Create dummy package.json
    pkg_file = tmp_path / "package.json"
    pkg_file.write_text(json.dumps({"name": "test-pkg", "license": "MIT"}), encoding="utf-8")

    asset1 = ledger.scan_and_register_package(
        asset_id="pkg-1",
        asset_type="npm_package",
        manifest_path=str(pkg_file),
    )
    assert asset1.detected_license.spdx_id == "MIT"

    # Register AGPL asset
    ledger.scan_and_register_package(
        asset_id="skill-agpl",
        asset_type="skill",
        declared_license="AGPL-3.0",
        package_url="pkg:generic/skill-agpl@1.0.0",
    )

    # Summarize under cloud commercial
    summary = ledger.summarize(environment=DeploymentEnvironment.CLOUD_COMMERCIAL)
    assert summary.total_assets == 2
    assert summary.permissive_count == 1
    assert summary.strong_copyleft_count == 1
    assert summary.has_blocking_violations is True

    # Summarize under local desktop
    summary_local = ledger.summarize(environment=DeploymentEnvironment.LOCAL_DESKTOP)
    assert summary_local.has_blocking_violations is False

    # CycloneDX export
    cyclonedx = ledger.export_cyclonedx_license_records()
    assert len(cyclonedx) == 2
    agpl_record = next(r for r in cyclonedx if r["bom-ref"] == "skill-agpl")
    assert agpl_record["copyleft"] == "true"
    assert agpl_record["commercial_friendly"] == "false"
    assert agpl_record["purl"] == "pkg:generic/skill-agpl@1.0.0"

    # Unregister
    assert ledger.unregister_asset("pkg-1") is True
    assert ledger.get_asset("pkg-1") is None
    assert len(ledger.list_assets()) == 1
