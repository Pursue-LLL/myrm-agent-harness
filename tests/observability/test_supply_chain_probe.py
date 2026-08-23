"""Unit tests for supply chain diagnostic probe."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.backends.skills.scanning.scanner import ScanSeverity
from myrm_agent_harness.backends.skills.scanning.security_advisories import AdvisoryFinding
from myrm_agent_harness.observability.diagnostics.supply_chain import check_supply_chain_health


@pytest.mark.asyncio
async def test_supply_chain_health_clean() -> None:
    mock_dist = MagicMock()
    mock_dist.metadata = {"Name": "pydantic"}
    mock_dist.version = "2.10.0"

    with (
        patch("importlib.metadata.distributions", return_value=[mock_dist]),
        patch(
            "myrm_agent_harness.observability.diagnostics.supply_chain.match_known_advisories",
            return_value=[],
        ),
        patch(
            "myrm_agent_harness.observability.diagnostics.supply_chain.query_osv_batch",
            AsyncMock(return_value=[]),
        ),
    ):
        report = await check_supply_chain_health()
        assert report.component_name == "SupplyChainSecurity"
        assert report.status == "pass"
        assert report.code == "OK_SUPPLY_CHAIN_HEALTHY"
        assert report.meta_data is not None
        assert report.meta_data["packages_scanned_count"] == 1
        assert report.meta_data["critical_vuln_count"] == 0


@pytest.mark.asyncio
async def test_supply_chain_health_critical_finding() -> None:
    mock_dist = MagicMock()
    mock_dist.metadata = {"Name": "malicious-pkg"}
    mock_dist.version = "1.0.0"

    crit_finding = AdvisoryFinding(
        advisory_id="MAL-2026-001",
        package_name="malicious-pkg",
        ecosystem="PyPI",
        severity=ScanSeverity.CRITICAL,
        title="Token Stealer Malware",
        description="Extracts environment tokens",
        matched_version="1.0.0",
    )

    with (
        patch("importlib.metadata.distributions", return_value=[mock_dist]),
        patch(
            "myrm_agent_harness.observability.diagnostics.supply_chain.match_known_advisories",
            return_value=[crit_finding],
        ),
        patch(
            "myrm_agent_harness.observability.diagnostics.supply_chain.query_osv_batch",
            AsyncMock(return_value=[]),
        ),
    ):
        report = await check_supply_chain_health()
        assert report.component_name == "SupplyChainSecurity"
        assert report.status == "fail"
        assert report.code == "ERR_SUPPLY_CHAIN_CRITICAL_MALWARE"
        assert report.meta_data is not None
        assert report.meta_data["critical_vuln_count"] == 1
        assert report.fix_suggestion is not None
