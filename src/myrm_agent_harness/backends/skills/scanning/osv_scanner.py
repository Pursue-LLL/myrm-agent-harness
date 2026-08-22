"""OSV.dev Batch Vulnerability and Supply Chain Scanner.

Provides asynchronous querying of OSV.dev (Open Source Vulnerabilities) API
with query batching, local TTL caching, and graceful offline fallback.

[INPUT]
- DeclaredDependency (from dependency_extractor)
- VulnScanCache (from vuln_cache)
- ScanSeverity (from scanner)
- AdvisoryFinding (from security_advisories)

[OUTPUT]
- query_osv_batch: batch scan declared dependencies against OSV.dev
- parse_osv_severity: map OSV severity/CVSS/database_specific to ScanSeverity

[POS]
Online vulnerability intelligence provider for skill supply chain security.
"""

from __future__ import annotations

import logging
import re
from typing import Sequence

from myrm_agent_harness.backends.skills.scanning.dependency_extractor import DeclaredDependency
from myrm_agent_harness.backends.skills.scanning.scanner import ScanSeverity
from myrm_agent_harness.backends.skills.scanning.security_advisories import AdvisoryFinding
from myrm_agent_harness.backends.skills.scanning.vuln_cache import VulnScanCache, get_vuln_cache
from myrm_agent_harness.infra.tls_compat import create_httpx_client

logger = logging.getLogger(__name__)

_OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"
_OSV_TIMEOUT_SECONDS = 5.0
_MAX_BATCH_SIZE = 100


def parse_osv_severity(vuln_data: dict[str, object]) -> ScanSeverity:
    """Map OSV vulnerability data (CVSS / database_specific / ID prefix) to ScanSeverity."""
    vuln_id = str(vuln_data.get("id", "")).upper()
    if vuln_id.startswith("MAL-"):
        return ScanSeverity.CRITICAL

    # 1. Check database_specific severity
    db_spec = vuln_data.get("database_specific")
    if isinstance(db_spec, dict):
        db_sev = str(db_spec.get("severity", "")).upper()
        if "CRITICAL" in db_sev:
            return ScanSeverity.CRITICAL
        if "HIGH" in db_sev:
            return ScanSeverity.HIGH
        if "MODERATE" in db_sev or "MEDIUM" in db_sev:
            return ScanSeverity.MEDIUM
        if "LOW" in db_sev:
            return ScanSeverity.LOW

    # 2. Check CVSS severity array
    severities = vuln_data.get("severity")
    if isinstance(severities, list):
        for item in severities:
            if isinstance(item, dict):
                score_str = str(item.get("score", ""))
                # Extract numerical CVSS score if available
                # Often in format "CVSS:3.1/AV:N/... (9.8)" or just "9.8" or "CVSS:3.1/..."
                # Extract all floating point numbers or numbers inside parentheses
                paren_match = re.search(r"\(\s*(\d+(?:\.\d+)?)\s*\)", score_str)
                if paren_match:
                    val = float(paren_match.group(1))
                    if 0.0 <= val <= 10.0:
                        if val >= 9.0:
                            return ScanSeverity.CRITICAL
                        if val >= 7.0:
                            return ScanSeverity.HIGH
                        if val >= 4.0:
                            return ScanSeverity.MEDIUM
                        return ScanSeverity.LOW

                # If no parenthesis, check raw score number
                try:
                    val = float(score_str)
                    if 0.0 <= val <= 10.0:
                        if val >= 9.0:
                            return ScanSeverity.CRITICAL
                        if val >= 7.0:
                            return ScanSeverity.HIGH
                        if val >= 4.0:
                            return ScanSeverity.MEDIUM
                        return ScanSeverity.LOW
                except ValueError:
                    pass

    # Default fallback for unknown severity vulnerability
    return ScanSeverity.MEDIUM


def _normalize_exact_version(version_spec: str) -> str | None:
    """Extract exact version string if pinned with == or exact numbers, else None."""
    spec = version_spec.strip()
    if not spec:
        return None
    match = re.match(r"^==?\s*([0-9A-Za-z._-]+)$", spec)
    if match:
        return match.group(1).strip()
    if re.match(r"^[0-9]+(?:\.[0-9A-Za-z._-]+)+$", spec):
        return spec
    return None


async def query_osv_batch(
    dependencies: Sequence[DeclaredDependency],
    *,
    cache: VulnScanCache | None = None,
    timeout_seconds: float = _OSV_TIMEOUT_SECONDS,
) -> list[AdvisoryFinding]:
    """Query OSV.dev in batch for declared dependencies.

    Args:
        dependencies: List of dependencies extracted from manifests.
        cache: Optional VulnScanCache instance (uses default global cache if None).
        timeout_seconds: HTTP request timeout in seconds.

    Returns:
        List of AdvisoryFinding discovered from OSV.
    """
    if not dependencies:
        return []

    active_cache = cache if cache is not None else get_vuln_cache()
    findings: list[AdvisoryFinding] = []
    uncached_deps: list[DeclaredDependency] = []

    # 1. Check cache first
    for dep in dependencies:
        cached = active_cache.get(dep.ecosystem, dep.name, dep.version_spec)
        if cached is not None:
            # Re-attach file_path to cached findings for precision
            for cf in cached:
                findings.append(
                    AdvisoryFinding(
                        advisory_id=cf.advisory_id,
                        package_name=cf.package_name,
                        ecosystem=cf.ecosystem,
                        severity=cf.severity,
                        title=cf.title,
                        description=cf.description,
                        matched_version=dep.version_spec,
                        file_path=dep.file_path,
                        is_acked=cf.is_acked,
                        source="osv_api",
                    )
                )
        else:
            uncached_deps.append(dep)

    if not uncached_deps:
        return findings

    # 2. Build OSV query batches
    for i in range(0, len(uncached_deps), _MAX_BATCH_SIZE):
        batch = uncached_deps[i : i + _MAX_BATCH_SIZE]
        queries: list[dict[str, object]] = []
        for dep in batch:
            query_obj: dict[str, object] = {
                "package": {
                    "name": dep.name,
                    "ecosystem": dep.ecosystem,
                }
            }
            exact_ver = _normalize_exact_version(dep.version_spec)
            if exact_ver:
                query_obj["version"] = exact_ver
            queries.append(query_obj)

        try:
            async with create_httpx_client(timeout=timeout_seconds) as client:
                response = await client.post(
                    _OSV_QUERYBATCH_URL,
                    json={"queries": queries},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.debug("OSV batch query failed or timed out: %s", exc)
            # Fail-open / graceful fallback: skip online check on network failure
            continue

        results = payload.get("results", [])
        if not isinstance(results, list):
            continue

        for dep, res_obj in zip(batch, results):
            dep_findings: list[AdvisoryFinding] = []
            if isinstance(res_obj, dict):
                vulns = res_obj.get("vulns", [])
                if isinstance(vulns, list):
                    for vuln in vulns:
                        if isinstance(vuln, dict):
                            adv_id = str(vuln.get("id", "UNKNOWN-VULN"))
                            summary = str(vuln.get("summary") or vuln.get("details") or "Vulnerability advisory")
                            sev = parse_osv_severity(vuln)
                            finding = AdvisoryFinding(
                                advisory_id=adv_id,
                                package_name=dep.name,
                                ecosystem=dep.ecosystem,
                                severity=sev,
                                title=summary[:200],
                                description=str(vuln.get("details", summary))[:500],
                                matched_version=dep.version_spec or "*",
                                file_path=dep.file_path,
                                is_acked=False,
                                source="osv_api",
                            )
                            dep_findings.append(finding)
                            findings.append(finding)

            # Update cache for this dependency (even if empty to cache clean state)
            active_cache.set(dep.ecosystem, dep.name, dep.version_spec, dep_findings)

    return findings
