"""Offline Known-Compromised Package Advisories Catalog.

Provides zero-latency, offline matching for famous supply-chain malware,
hijacked packages, protestware, and token stealers across npm and PyPI ecosystems.

[INPUT]
- DeclaredDependency (from dependency_extractor)
- ScanSeverity (from scanner)

[OUTPUT]
- KnownAdvisory: immutable advisory definition
- AdvisoryFinding: finding produced when a declared dependency matches a compromised advisory
- match_known_advisories: evaluate declared dependencies against offline advisory catalog
- get_known_advisories_catalog: return the list of registered advisories

[POS]
Offline security gate for skill supply chain. Provides instant, deterministic detection
of notorious malware packages without depending on external network access.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Sequence

from myrm_agent_harness.backends.skills.scanning.dependency_extractor import DeclaredDependency
from myrm_agent_harness.backends.skills.scanning.scanner import ScanSeverity

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class KnownAdvisory:
    """A known compromised package security advisory."""

    advisory_id: str
    package_name: str
    ecosystem: str  # "npm" or "PyPI"
    affected_versions: tuple[str, ...]
    severity: ScanSeverity
    title: str
    description: str
    cve_id: str = ""


@dataclass(frozen=True, slots=True)
class AdvisoryFinding:
    """A finding when a declared dependency matches a known vulnerability/advisory."""

    advisory_id: str
    package_name: str
    ecosystem: str
    severity: ScanSeverity
    title: str
    description: str
    matched_version: str
    file_path: str = ""
    is_acked: bool = False
    source: str = "offline_advisory"  # "offline_advisory" | "osv_api"


_BUILTIN_ADVISORIES: tuple[KnownAdvisory, ...] = (
    # 1. npm: event-stream (3.3.6) / flatmap-stream (0.1.1)
    KnownAdvisory(
        advisory_id="MAL-2018-001",
        package_name="event-stream",
        ecosystem="npm",
        affected_versions=("==3.3.6", "3.3.6"),
        severity=ScanSeverity.CRITICAL,
        title="Malicious flatmap-stream dependency injection",
        description="Version 3.3.6 contained flatmap-stream to steal Bitcoin wallets from Copay application.",
        cve_id="CVE-2018-3721",
    ),
    KnownAdvisory(
        advisory_id="MAL-2018-002",
        package_name="flatmap-stream",
        ecosystem="npm",
        affected_versions=("*",),
        severity=ScanSeverity.CRITICAL,
        title="Malicious package used in Copay wallet theft",
        description="Entire flatmap-stream package is malicious and intended for target payload delivery.",
    ),
    # 2. npm: ua-parser-js (0.7.29, 0.8.0, 1.0.0)
    KnownAdvisory(
        advisory_id="MAL-2021-001",
        package_name="ua-parser-js",
        ecosystem="npm",
        affected_versions=("==0.7.29", "0.7.29", "==0.8.0", "0.8.0", "==1.0.0", "1.0.0"),
        severity=ScanSeverity.CRITICAL,
        title="Hijacked package releasing cryptominer and password stealer",
        description="Attacker hijacked npm account and published trojanized versions containing Danabot/XMRig miners.",
        cve_id="CVE-2021-43616",
    ),
    # 3. npm: colors (1.4.1, 1.4.44-liberty-2.0.0) & faker (6.6.6)
    KnownAdvisory(
        advisory_id="MAL-2022-001",
        package_name="colors",
        ecosystem="npm",
        affected_versions=("==1.4.1", "1.4.1", "==1.4.44-liberty-2.0.0", "1.4.44-liberty-2.0.0"),
        severity=ScanSeverity.HIGH,
        title="Self-sabotage infinite loop denial of service",
        description="Maintainer published corrupted version with infinite loop and garbage text output.",
    ),
    KnownAdvisory(
        advisory_id="MAL-2022-002",
        package_name="faker",
        ecosystem="npm",
        affected_versions=("==6.6.6", "6.6.6"),
        severity=ScanSeverity.HIGH,
        title="Self-sabotage release",
        description="Maintainer emptied source files and published protest commit.",
    ),
    # 4. npm: node-ipc (>=10.1.1, <=10.1.2)
    KnownAdvisory(
        advisory_id="MAL-2022-003",
        package_name="node-ipc",
        ecosystem="npm",
        affected_versions=("==10.1.1", "10.1.1", "==10.1.2", "10.1.2", "==11.0.0", "11.0.0"),
        severity=ScanSeverity.CRITICAL,
        title="Protestware file wiper targeting specific geographical IPs",
        description="Included peacetime module that overwrote files on disk with heart symbols.",
        cve_id="CVE-2022-23812",
    ),
    # 5. PyPI: ctx (0.1.2)
    KnownAdvisory(
        advisory_id="MAL-2022-004",
        package_name="ctx",
        ecosystem="PyPI",
        affected_versions=("==0.1.2", "0.1.2"),
        severity=ScanSeverity.CRITICAL,
        title="Hijacked PyPI package exfiltrating environment variables and AWS keys",
        description="Attacker registered expired domain of original author to claim PyPI package and exfiltrate env vars.",
    ),
    # 6. PyPI: typosquatting and token stealers
    KnownAdvisory(
        advisory_id="MAL-2023-001",
        package_name="py-coordle",
        ecosystem="PyPI",
        affected_versions=("*",),
        severity=ScanSeverity.CRITICAL,
        title="Typosquatting Discord token and browser credential stealer",
        description="Malicious package designed to steal Discord tokens and browser data upon import.",
    ),
    KnownAdvisory(
        advisory_id="MAL-2023-002",
        package_name="requests-oauth",
        ecosystem="PyPI",
        affected_versions=("*",),
        severity=ScanSeverity.CRITICAL,
        title="Typosquatting package containing obfuscated reverse shell",
        description="Typosquatting requests-oauthlib with reverse shell backdoor in setup.py.",
    ),
    KnownAdvisory(
        advisory_id="MAL-2023-003",
        package_name="colorama-v2",
        ecosystem="PyPI",
        affected_versions=("*",),
        severity=ScanSeverity.CRITICAL,
        title="Typosquatting malware package targeting developers",
        description="Impersonates colorama package with malicious payload.",
    ),
    KnownAdvisory(
        advisory_id="MAL-2024-001",
        package_name="noblesse",
        ecosystem="PyPI",
        affected_versions=("*",),
        severity=ScanSeverity.CRITICAL,
        title="Token grabber and info-stealer package",
        description="Malware package on PyPI harvesting system information and browser credentials.",
    ),
    KnownAdvisory(
        advisory_id="MAL-2024-002",
        package_name="discord-selfbot-v14",
        ecosystem="npm",
        affected_versions=("*",),
        severity=ScanSeverity.CRITICAL,
        title="Malicious npm package with remote payload execution",
        description="Downloads and executes obfuscated remote payloads upon installation.",
    ),
)


def get_known_advisories_catalog() -> tuple[KnownAdvisory, ...]:
    """Get the immutable catalog of built-in known compromised advisories."""
    return _BUILTIN_ADVISORIES


def _normalize_version_string(ver: str) -> str:
    """Normalize a version string by stripping operators and prefixes."""
    ver = ver.strip()
    ver = re.sub(r"^[=^~><\s]+", "", ver).strip()
    return ver


def _is_version_affected(declared_spec: str, affected_specs: Sequence[str]) -> bool:
    """Check if declared version matches any affected version specifier."""
    if not affected_specs:
        return False

    if "*" in affected_specs:
        return True

    clean_declared = _normalize_version_string(declared_spec)
    if not clean_declared:
        # If no version specified or wildcard, assume potential match for strict safety
        return True

    for affected in affected_specs:
        clean_affected = _normalize_version_string(affected)
        if clean_declared == clean_affected:
            return True
        if clean_declared.startswith(clean_affected) or clean_affected.startswith(clean_declared):
            return True

    return False


def match_known_advisories(
    dependencies: list[DeclaredDependency],
    catalog: Sequence[KnownAdvisory] | None = None,
) -> list[AdvisoryFinding]:
    """Match declared dependencies against the known compromised advisories catalog."""
    if catalog is None:
        catalog = _BUILTIN_ADVISORIES

    findings: list[AdvisoryFinding] = []
    # Build lookup map: (normalized_name, ecosystem.lower()) -> list[KnownAdvisory]
    lookup: dict[tuple[str, str], list[KnownAdvisory]] = {}
    for adv in catalog:
        key = (adv.package_name.lower(), adv.ecosystem.lower())
        lookup.setdefault(key, []).append(adv)

    for dep in dependencies:
        key = (dep.name.lower(), dep.ecosystem.lower())
        matched_advisories = lookup.get(key)
        if not matched_advisories:
            continue

        for adv in matched_advisories:
            if _is_version_affected(dep.version_spec, adv.affected_versions):
                findings.append(
                    AdvisoryFinding(
                        advisory_id=adv.advisory_id,
                        package_name=dep.name,
                        ecosystem=adv.ecosystem,
                        severity=adv.severity,
                        title=adv.title,
                        description=adv.description,
                        matched_version=dep.version_spec or "*",
                        file_path=dep.file_path,
                        is_acked=False,
                        source="offline_advisory",
                    )
                )

    return findings
