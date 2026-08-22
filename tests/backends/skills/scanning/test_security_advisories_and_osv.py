"""Tests for security_advisories.py, vuln_cache.py, and osv_scanner.py."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from myrm_agent_harness.backends.skills.scanning.dependency_extractor import DeclaredDependency
from myrm_agent_harness.backends.skills.scanning.osv_scanner import (
    parse_osv_severity,
    query_osv_batch,
)
from myrm_agent_harness.backends.skills.scanning.scanner import ScanSeverity
from myrm_agent_harness.backends.skills.scanning.security_advisories import (
    AdvisoryFinding,
    get_known_advisories_catalog,
    match_known_advisories,
)
from myrm_agent_harness.backends.skills.scanning.vuln_cache import (
    VulnScanCache,
    get_vuln_cache,
)


def test_known_advisories_catalog_and_match() -> None:
    catalog = get_known_advisories_catalog()
    assert len(catalog) >= 10

    # 1. Match compromised event-stream
    deps = [
        DeclaredDependency(
            name="event-stream",
            version_spec="3.3.6",
            ecosystem="npm",
        ),
        DeclaredDependency(
            name="safe-package",
            version_spec="1.0.0",
            ecosystem="npm",
        ),
    ]
    findings = match_known_advisories(deps)
    assert len(findings) == 1
    assert findings[0].advisory_id == "MAL-2018-001"
    assert findings[0].severity == ScanSeverity.CRITICAL

    # 2. Match hijacked ctx package on PyPI
    pypi_deps = [
        DeclaredDependency(
            name="ctx",
            version_spec="==0.1.2",
            ecosystem="PyPI",
        )
    ]
    pypi_findings = match_known_advisories(pypi_deps)
    assert len(pypi_findings) == 1
    assert pypi_findings[0].advisory_id == "MAL-2022-004"


def test_vuln_cache_lifecycle(tmp_path: Path) -> None:
    cache = VulnScanCache(default_ttl_seconds=10.0)
    assert cache.get("npm", "pkg-a", "1.0.0") is None

    finding = AdvisoryFinding(
        advisory_id="TEST-001",
        package_name="pkg-a",
        ecosystem="npm",
        severity=ScanSeverity.HIGH,
        title="Test vuln",
        description="Detail",
        matched_version="1.0.0",
    )
    cache.set("npm", "pkg-a", "1.0.0", [finding])

    hit = cache.get("npm", "pkg-a", "1.0.0")
    assert hit is not None
    assert len(hit) == 1
    assert hit[0].advisory_id == "TEST-001"

    # Disk persist & load
    cache_file = tmp_path / "vuln_cache.json"
    assert cache.save_to_disk(cache_file) is True
    assert cache_file.exists()

    new_cache = VulnScanCache()
    assert new_cache.load_from_disk(cache_file) is True
    new_hit = new_cache.get("npm", "pkg-a", "1.0.0")
    assert new_hit is not None
    assert len(new_hit) == 1

    # Prune and clear
    assert cache.prune_expired() == 0
    cache.clear()
    assert cache.get("npm", "pkg-a", "1.0.0") is None


def test_query_osv_batch_empty_and_cached() -> None:
    import asyncio
    cache = VulnScanCache()
    assert asyncio.run(query_osv_batch([], cache=cache)) == []

    # Dep with existing cache
    f = AdvisoryFinding(
        advisory_id="GHSA-999",
        package_name="cached-pkg",
        ecosystem="npm",
        severity=ScanSeverity.HIGH,
        title="Cached",
        description="Detail",
        matched_version="1.0.0",
    )
    cache.set("npm", "cached-pkg", "1.0.0", [f])
    dep = DeclaredDependency(name="cached-pkg", version_spec="1.0.0", ecosystem="npm")
    res = asyncio.run(query_osv_batch([dep], cache=cache))
    assert len(res) == 1
    assert res[0].advisory_id == "GHSA-999"


def test_vuln_cache_default_singleton() -> None:
    from myrm_agent_harness.backends.skills.scanning.vuln_cache import get_vuln_cache
    c = get_vuln_cache()
    assert c is not None
    assert isinstance(c, VulnScanCache)


@pytest.mark.asyncio
async def test_query_osv_batch_success() -> None:
    cache = VulnScanCache()
    deps = [
        DeclaredDependency(name="bad-pkg", version_spec="1.0.0", ecosystem="npm"),
    ]

    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={
            "results": [
                {
                    "vulns": [
                        {
                            "id": "MAL-2024-099",
                            "summary": "Malicious package on npm",
                            "details": "Details here",
                        }
                    ]
                }
            ]
        }
    )

    with patch("myrm_agent_harness.backends.skills.scanning.osv_scanner.create_httpx_client") as mock_client_cls:
        client_instance = AsyncMock()
        client_instance.__aenter__.return_value = client_instance
        client_instance.__aexit__.return_value = None
        client_instance.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = client_instance

        findings = await query_osv_batch(deps, cache=cache)
        assert len(findings) == 1
        assert findings[0].advisory_id == "MAL-2024-099"
        assert findings[0].severity == ScanSeverity.CRITICAL

        # Verify cached
        cached = cache.get("npm", "bad-pkg", "1.0.0")
        assert cached is not None
        assert len(cached) == 1
