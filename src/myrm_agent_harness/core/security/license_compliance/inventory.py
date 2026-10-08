"""License inventory tracking, scanning, and SBOM-compatible ledger.

[INPUT]
- Asset descriptions, metadata dictionaries, or local file contents.

[OUTPUT]
- Managed inventory ledger, aggregated LicenseInventorySummary, and CycloneDX-compatible data structures.

[POS]
- Harness core security inventory tracking third-party licenses across runtime sessions.
"""

from __future__ import annotations

import json
from pathlib import Path

from myrm_agent_harness.core.security.license_compliance.gating import LicenseComplianceGate
from myrm_agent_harness.core.security.license_compliance.spdx_registry import SpdxLicenseRegistry
from myrm_agent_harness.core.security.license_compliance.types import (
    AssetLicenseDescriptor,
    DeploymentEnvironment,
    LicenseGateDecision,
    LicenseInventorySummary,
    LicenseRiskTier,
)


class LicenseInventoryLedger:
    """Manages active third-party assets and evaluates overall system compliance posture."""

    def __init__(self, gate: LicenseComplianceGate | None = None) -> None:
        self._gate = gate or LicenseComplianceGate()
        self._assets: dict[str, AssetLicenseDescriptor] = {}

    def register_asset(self, asset: AssetLicenseDescriptor) -> AssetLicenseDescriptor:
        """Register or update an asset license descriptor in the active ledger."""
        self._assets[asset.asset_id] = asset
        return asset

    def unregister_asset(self, asset_id: str) -> bool:
        """Remove an asset from the ledger by its identifier."""
        if asset_id in self._assets:
            del self._assets[asset_id]
            return True
        return False

    def get_asset(self, asset_id: str) -> AssetLicenseDescriptor | None:
        """Retrieve an asset descriptor if present."""
        return self._assets.get(asset_id)

    def list_assets(self) -> tuple[AssetLicenseDescriptor, ...]:
        """Return all tracked asset descriptors as an immutable tuple."""
        return tuple(self._assets.values())

    def scan_and_register_package(
        self,
        asset_id: str,
        asset_type: str,
        declared_license: str | None = None,
        manifest_path: str | None = None,
        package_url: str | None = None,
    ) -> AssetLicenseDescriptor:
        """Infer license from declared identifier or manifest file and register into ledger."""
        license_string = declared_license

        if not license_string and manifest_path:
            p = Path(manifest_path)
            if p.is_file():
                if p.name == "package.json":
                    try:
                        content = json.loads(p.read_text(encoding="utf-8"))
                        if isinstance(content, dict) and "license" in content:
                            raw_val = content["license"]
                            if isinstance(raw_val, str):
                                license_string = raw_val
                            elif isinstance(raw_val, dict) and "type" in raw_val:
                                license_string = str(raw_val["type"])
                    except Exception:
                        pass
                elif p.name in {"LICENSE", "LICENSE.txt", "LICENSE.md"}:
                    # Read header line
                    first_lines = p.read_text(encoding="utf-8")[:500]
                    license_string = first_lines

        detected = SpdxLicenseRegistry.normalize(license_string)
        descriptor = AssetLicenseDescriptor(
            asset_id=asset_id,
            asset_type=asset_type,
            detected_license=detected,
            license_file_path=manifest_path,
            package_url=package_url,
        )
        return self.register_asset(descriptor)

    def summarize(
        self, environment: DeploymentEnvironment = DeploymentEnvironment.CLOUD_COMMERCIAL
    ) -> LicenseInventorySummary:
        """Generate an aggregated summary across all tracked assets."""
        assets_tuple = self.list_assets()
        total = len(assets_tuple)
        permissive = 0
        weak = 0
        strong = 0
        unknown = 0
        has_violations = False

        for asset in assets_tuple:
            tier = asset.detected_license.risk_tier
            if tier == LicenseRiskTier.PERMISSIVE:
                permissive += 1
            elif tier == LicenseRiskTier.WEAK_COPYLEFT:
                weak += 1
            elif tier == LicenseRiskTier.STRONG_COPYLEFT:
                strong += 1
            elif tier == LicenseRiskTier.UNKNOWN:
                unknown += 1

            verdict = self._gate.evaluate(asset=asset, environment=environment)
            if verdict.decision in {
                LicenseGateDecision.BLOCKED_COPYLEFT_RESTRICTION,
                LicenseGateDecision.BLOCKED_UNKNOWN_LICENSE,
            }:
                has_violations = True

        return LicenseInventorySummary(
            total_assets=total,
            permissive_count=permissive,
            weak_copyleft_count=weak,
            strong_copyleft_count=strong,
            unknown_count=unknown,
            has_blocking_violations=has_violations,
            assets=assets_tuple,
        )

    def export_cyclonedx_license_records(self) -> list[dict[str, str]]:
        """Export inventory assets formatted as CycloneDX-compliant license records."""
        records: list[dict[str, str]] = []
        for asset in self._assets.values():
            meta = asset.detected_license
            record: dict[str, str] = {
                "bom-ref": asset.asset_id,
                "type": asset.asset_type,
                "license_id": meta.spdx_id,
                "license_name": meta.raw_name,
                "risk_tier": meta.risk_tier.value,
                "copyleft": "true" if meta.is_copyleft else "false",
                "commercial_friendly": "true" if meta.commercial_friendly else "false",
            }
            if asset.package_url:
                record["purl"] = asset.package_url
            records.append(record)
        return records
