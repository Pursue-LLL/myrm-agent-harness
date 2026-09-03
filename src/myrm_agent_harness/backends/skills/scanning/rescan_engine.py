"""Installed Skill Supply Chain Rescan Engine.

Orchestrates multi-layer security scanning across installed and in-quarantine skills:
1. Static code scanning (regex patterns & AST analysis)
2. Lifecycle script gate checks (preinstall, install, postinstall)
3. Dependency extraction (package.json, requirements.txt, pyproject.toml)
4. Offline known-compromised package advisory matching
5. Online OSV.dev batch vulnerability intelligence
6. User advisory acknowledgment (AdvisoryAckRegistry) governance

[INPUT]
- DeclaredDependency, extract_skill_dependencies, extract_dependencies_from_files (from dependency_extractor)
- KnownAdvisory, AdvisoryFinding, match_known_advisories (from security_advisories)
- query_osv_batch (from osv_scanner)
- VulnScanCache, get_vuln_cache (from vuln_cache)
- scan_skill_directory, ScanFinding, ScanResult, ScanSeverity, SkillTrustRecommendation (from scanner)
- PackageAuditFinding, check_lifecycle_scripts, audit_skill_directory (from package_audit)
- AstScanFinding, analyze_python_ast (from ast_analyzer)

[OUTPUT]
- AdvisoryAck: user acknowledgment metadata for a specific vulnerability/advisory
- AdvisoryAckRegistry: store and governance for acknowledged advisories
- SkillRescanResult: complete aggregated security and supply-chain assessment
- InstalledSkillRescanEngine: rescan engine for on-demand and periodic skill auditing
- get_rescan_engine: singleton accessor for the default rescan engine

[POS]
Core rescan engine for installed skills supply chain security governance.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from myrm_agent_harness.backends.skills.scanning.ast_analyzer import AstScanFinding
from myrm_agent_harness.backends.skills.scanning.dependency_extractor import (
    DeclaredDependency,
    extract_dependencies_from_files,
    extract_skill_dependencies,
)
from myrm_agent_harness.backends.skills.scanning.osv_scanner import query_osv_batch
from myrm_agent_harness.backends.skills.scanning.package_audit import (
    PackageAuditFinding,
    audit_skill_directory,
    check_lifecycle_scripts,
)
from myrm_agent_harness.backends.skills.scanning.scanner import (
    ScanFinding,
    ScanSeverity,
    SkillTrustRecommendation,
    scan_skill_content,
    scan_skill_directory,
)
from myrm_agent_harness.backends.skills.scanning.security_advisories import (
    AdvisoryFinding,
    match_known_advisories,
)
from myrm_agent_harness.backends.skills.scanning.vuln_cache import VulnScanCache, get_vuln_cache

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AdvisoryAck:
    """User acknowledgment metadata for a vulnerability finding."""

    advisory_id: str
    package_name: str
    reason: str
    acked_at: float = field(default_factory=time.time)
    acked_by: str = "user"


class AdvisoryAckRegistry:
    """Store for user-acknowledged advisories and vulnerabilities."""

    def __init__(self) -> None:
        self._acks: dict[tuple[str, str], AdvisoryAck] = {}

    def _make_key(self, advisory_id: str, package_name: str) -> tuple[str, str]:
        return (advisory_id.strip().upper(), package_name.strip().lower())

    def ack_advisory(
        self,
        advisory_id: str,
        package_name: str,
        reason: str = "",
        acked_by: str = "user",
    ) -> AdvisoryAck:
        """Acknowledge / dismiss an advisory finding."""
        key = self._make_key(advisory_id, package_name)
        ack = AdvisoryAck(
            advisory_id=advisory_id.strip().upper(),
            package_name=package_name.strip().lower(),
            reason=reason.strip(),
            acked_at=time.time(),
            acked_by=acked_by.strip() or "user",
        )
        self._acks[key] = ack
        return ack

    def unack_advisory(self, advisory_id: str, package_name: str) -> bool:
        """Remove acknowledgment for an advisory."""
        key = self._make_key(advisory_id, package_name)
        return self._acks.pop(key, None) is not None

    def is_acked(self, advisory_id: str, package_name: str) -> bool:
        """Check if an advisory has been acknowledged."""
        key = self._make_key(advisory_id, package_name)
        return key in self._acks

    def get_ack(self, advisory_id: str, package_name: str) -> AdvisoryAck | None:
        """Get the acknowledgment metadata if present."""
        key = self._make_key(advisory_id, package_name)
        return self._acks.get(key)

    def list_acks(self) -> list[AdvisoryAck]:
        """List all acknowledged advisories."""
        return list(self._acks.values())

    def save_to_disk(self, file_path: Path | str) -> bool:
        """Save acknowledgments to JSON file."""
        target = Path(file_path).resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            data = [
                {
                    "advisory_id": ack.advisory_id,
                    "package_name": ack.package_name,
                    "reason": ack.reason,
                    "acked_at": ack.acked_at,
                    "acked_by": ack.acked_by,
                }
                for ack in self._acks.values()
            ]
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except Exception as exc:
            logger.debug("Failed to save advisory acks to %s: %s", target, exc)
            return False

    def load_from_disk(self, file_path: Path | str) -> bool:
        """Load acknowledgments from JSON file."""
        target = Path(file_path).resolve()
        if not target.is_file():
            return False
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return False
            for item in data:
                if isinstance(item, dict):
                    adv_id = str(item.get("advisory_id", ""))
                    pkg_name = str(item.get("package_name", ""))
                    reason = str(item.get("reason", ""))
                    acked_at = float(item.get("acked_at", time.time()))
                    acked_by = str(item.get("acked_by", "user"))
                    if adv_id and pkg_name:
                        key = self._make_key(adv_id, pkg_name)
                        self._acks[key] = AdvisoryAck(
                            advisory_id=adv_id.strip().upper(),
                            package_name=pkg_name.strip().lower(),
                            reason=reason,
                            acked_at=acked_at,
                            acked_by=acked_by,
                        )
            return True
        except Exception as exc:
            logger.debug("Failed to load advisory acks from %s: %s", target, exc)
            return False


@dataclass
class SkillRescanResult:
    """Aggregated rescan assessment result for a skill."""

    skill_name: str
    skill_dir: str = ""
    recommendation: SkillTrustRecommendation = SkillTrustRecommendation.TRUSTED
    declared_dependencies: list[DeclaredDependency] = field(default_factory=list)
    advisory_findings: list[AdvisoryFinding] = field(default_factory=list)
    code_findings: list[ScanFinding] = field(default_factory=list)
    lifecycle_findings: list[PackageAuditFinding] = field(default_factory=list)
    ast_findings: list[AstScanFinding] = field(default_factory=list)
    scan_duration_ms: float = 0.0

    @property
    def is_clean(self) -> bool:
        return (
            len(self.unacked_advisory_findings) == 0
            and len(self.code_findings) == 0
            and len(self.lifecycle_findings) == 0
            and len(self.ast_findings) == 0
        )

    @property
    def unacked_advisory_findings(self) -> list[AdvisoryFinding]:
        return [f for f in self.advisory_findings if not f.is_acked]

    @property
    def acked_advisory_findings(self) -> list[AdvisoryFinding]:
        return [f for f in self.advisory_findings if f.is_acked]

    @property
    def has_critical_or_malware(self) -> bool:
        # Check active code/lifecycle/advisory findings for CRITICAL severity
        if any(f.severity == ScanSeverity.CRITICAL for f in self.code_findings):
            return True
        if any(f.severity in ("critical", "high") for f in self.lifecycle_findings):
            return True
        if any(f.severity == "critical" for f in self.ast_findings):
            return True
        if any(f.severity == ScanSeverity.CRITICAL for f in self.unacked_advisory_findings):
            return True
        return False

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if self.unacked_advisory_findings:
            parts.append(f"{len(self.unacked_advisory_findings)} supply-chain advisories")
        if self.code_findings:
            parts.append(f"{len(self.code_findings)} code findings")
        if self.lifecycle_findings:
            parts.append(f"{len(self.lifecycle_findings)} lifecycle script findings")
        if self.ast_findings:
            parts.append(f"{len(self.ast_findings)} AST findings")
        if not parts:
            return "No security issues detected (Clean)"
        return f"Found {', '.join(parts)} (Recommendation: {self.recommendation.value})"


class InstalledSkillRescanEngine:
    """Engine for running comprehensive supply chain and code rescans on skills."""

    def __init__(
        self,
        ack_registry: AdvisoryAckRegistry | None = None,
        vuln_cache: VulnScanCache | None = None,
    ) -> None:
        self.ack_registry = ack_registry if ack_registry is not None else AdvisoryAckRegistry()
        self.vuln_cache = vuln_cache if vuln_cache is not None else get_vuln_cache()

    def _compute_trust_recommendation(
        self,
        code_findings: Sequence[ScanFinding],
        lifecycle_findings: Sequence[PackageAuditFinding],
        ast_findings: Sequence[AstScanFinding],
        unacked_advisories: Sequence[AdvisoryFinding],
    ) -> SkillTrustRecommendation:
        """Compute trust recommendation based on unacked findings."""
        if any(f.severity == ScanSeverity.CRITICAL for f in code_findings):
            return SkillTrustRecommendation.REJECT
        if any(f.severity == "critical" for f in ast_findings):
            return SkillTrustRecommendation.REJECT
        if any(f.severity == "critical" for f in lifecycle_findings):
            return SkillTrustRecommendation.REJECT
        if any(f.severity == ScanSeverity.CRITICAL for f in unacked_advisories):
            return SkillTrustRecommendation.REJECT

        if any(f.severity == ScanSeverity.HIGH for f in code_findings):
            return SkillTrustRecommendation.UNTRUSTED
        if any(f.severity == "high" for f in ast_findings):
            return SkillTrustRecommendation.UNTRUSTED
        if any(f.severity == "high" for f in lifecycle_findings):
            return SkillTrustRecommendation.UNTRUSTED
        if any(f.severity == ScanSeverity.HIGH for f in unacked_advisories):
            return SkillTrustRecommendation.UNTRUSTED

        if code_findings or ast_findings or lifecycle_findings or unacked_advisories:
            return SkillTrustRecommendation.INSTALLED

        return SkillTrustRecommendation.TRUSTED

    async def rescan_skill_directory(
        self,
        skill_dir: Path | str,
        *,
        enable_online_osv: bool = True,
    ) -> SkillRescanResult:
        """Rescan an installed skill directory on disk."""
        start_time = time.perf_counter()
        target_path = Path(skill_dir).resolve()
        skill_name = target_path.name

        if not target_path.is_dir():
            return SkillRescanResult(
                skill_name=skill_name,
                skill_dir=str(target_path),
                recommendation=SkillTrustRecommendation.TRUSTED,
            )

        # 1. Static code scan
        code_scan_res = scan_skill_directory(skill_name, target_path)

        # 2. Lifecycle script audit
        lifecycle_findings = audit_skill_directory(target_path)

        # 3. Extract declared dependencies
        dependencies = extract_skill_dependencies(target_path)

        # 4. Offline known advisories match
        offline_findings = match_known_advisories(dependencies)

        # 5. Online OSV batch query (if enabled)
        online_findings: list[AdvisoryFinding] = []
        if enable_online_osv and dependencies:
            online_findings = await query_osv_batch(dependencies, cache=self.vuln_cache)

        # Deduplicate advisory findings by (advisory_id, package_name)
        seen_advisories: set[tuple[str, str]] = set()
        all_advisories: list[AdvisoryFinding] = []
        for adv in [*offline_findings, *online_findings]:
            adv_key = (adv.advisory_id.upper(), adv.package_name.lower())
            if adv_key not in seen_advisories:
                seen_advisories.add(adv_key)
                is_acked = self.ack_registry.is_acked(adv.advisory_id, adv.package_name)
                all_advisories.append(
                    AdvisoryFinding(
                        advisory_id=adv.advisory_id,
                        package_name=adv.package_name,
                        ecosystem=adv.ecosystem,
                        severity=adv.severity,
                        title=adv.title,
                        description=adv.description,
                        matched_version=adv.matched_version,
                        file_path=adv.file_path,
                        is_acked=is_acked,
                        source=adv.source,
                    )
                )

        unacked_advisories = [a for a in all_advisories if not a.is_acked]
        recommendation = self._compute_trust_recommendation(
            code_findings=code_scan_res.findings,
            lifecycle_findings=lifecycle_findings,
            ast_findings=code_scan_res.ast_findings,
            unacked_advisories=unacked_advisories,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return SkillRescanResult(
            skill_name=skill_name,
            skill_dir=str(target_path),
            recommendation=recommendation,
            declared_dependencies=dependencies,
            advisory_findings=all_advisories,
            code_findings=list(code_scan_res.findings),
            lifecycle_findings=lifecycle_findings,
            ast_findings=list(code_scan_res.ast_findings),
            scan_duration_ms=duration_ms,
        )

    async def rescan_in_memory_files(
        self,
        skill_name: str,
        files: dict[str, bytes],
        *,
        enable_online_osv: bool = True,
    ) -> SkillRescanResult:
        """Rescan an in-memory dictionary of files (e.g. during quarantine install)."""
        start_time = time.perf_counter()

        # 1. Lifecycle script check
        lifecycle_findings = check_lifecycle_scripts(files)

        # 2. Extract dependencies
        dependencies = extract_dependencies_from_files(files)

        # 3. Code scan across all text files
        code_findings: list[ScanFinding] = []
        ast_findings: list[AstScanFinding] = []
        for filename, content in files.items():
            if filename.endswith(".py"):
                text = content.decode("utf-8", errors="replace")
                code_findings.extend(scan_skill_content(text, filename).findings)
                ast_findings.extend(analyze_python_ast(text, filename))
            elif filename.endswith((".md", ".json", ".yaml", ".yml", ".sh", ".bash", ".js", ".ts")):
                text = content.decode("utf-8", errors="replace")
                code_findings.extend(scan_skill_content(text, filename).findings)

        # 4. Offline known advisories match
        offline_findings = match_known_advisories(dependencies)

        # 5. Online OSV batch query
        online_findings: list[AdvisoryFinding] = []
        if enable_online_osv and dependencies:
            online_findings = await query_osv_batch(dependencies, cache=self.vuln_cache)

        # Deduplicate and apply ack
        seen_advisories: set[tuple[str, str]] = set()
        all_advisories: list[AdvisoryFinding] = []
        for adv in [*offline_findings, *online_findings]:
            adv_key = (adv.advisory_id.upper(), adv.package_name.lower())
            if adv_key not in seen_advisories:
                seen_advisories.add(adv_key)
                is_acked = self.ack_registry.is_acked(adv.advisory_id, adv.package_name)
                all_advisories.append(
                    AdvisoryFinding(
                        advisory_id=adv.advisory_id,
                        package_name=adv.package_name,
                        ecosystem=adv.ecosystem,
                        severity=adv.severity,
                        title=adv.title,
                        description=adv.description,
                        matched_version=adv.matched_version,
                        file_path=adv.file_path,
                        is_acked=is_acked,
                        source=adv.source,
                    )
                )

        unacked_advisories = [a for a in all_advisories if not a.is_acked]
        recommendation = self._compute_trust_recommendation(
            code_findings=code_findings,
            lifecycle_findings=lifecycle_findings,
            ast_findings=ast_findings,
            unacked_advisories=unacked_advisories,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return SkillRescanResult(
            skill_name=skill_name,
            skill_dir="",
            recommendation=recommendation,
            declared_dependencies=dependencies,
            advisory_findings=all_advisories,
            code_findings=code_findings,
            lifecycle_findings=lifecycle_findings,
            ast_findings=ast_findings,
            scan_duration_ms=duration_ms,
        )

    async def rescan_all_installed_skills(
        self,
        installed_root: Path | str,
        *,
        enable_online_osv: bool = True,
    ) -> dict[str, SkillRescanResult]:
        """Rescan all installed skills under the given root directory."""
        root = Path(installed_root).resolve()
        if not root.is_dir():
            return {}

        results: dict[str, SkillRescanResult] = {}
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                res = await self.rescan_skill_directory(
                    child,
                    enable_online_osv=enable_online_osv,
                )
                results[child.name] = res

        return results


_GLOBAL_RESCAN_ENGINE = InstalledSkillRescanEngine()


def get_rescan_engine() -> InstalledSkillRescanEngine:
    """Get the global default rescan engine instance."""
    return _GLOBAL_RESCAN_ENGINE
