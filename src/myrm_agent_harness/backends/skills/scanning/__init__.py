"""Skill content security scanning subsystem.

Provides static pattern scanning (26 threat categories, 108 patterns),
Python AST analysis, package.json audit, multi-file directory scanning,
dependency extraction (package.json, requirements.txt, pyproject.toml),
offline known-compromised package advisories matching,
online OSV.dev batch vulnerability intelligence with TTL caching,
advisory acknowledgment governance (AdvisoryAckRegistry),
invisible Unicode detection, LLM-based semantic audit, persistent Volume cache,
and secure ZIP extraction with Zip Bomb / symlink / path traversal defense.
"""

from myrm_agent_harness.backends.skills.scanning.ast_analyzer import AstScanFinding, analyze_python_ast
from myrm_agent_harness.backends.skills.scanning.cache import (
    CacheStats,
    ScanResultCache,
    get_scan_cache,
)
from myrm_agent_harness.backends.skills.scanning.dependency_extractor import (
    DeclaredDependency,
    extract_dependencies_from_bun_lock,
    extract_dependencies_from_files,
    extract_dependencies_from_package_json,
    extract_dependencies_from_package_lock_json,
    extract_dependencies_from_pyproject_toml,
    extract_dependencies_from_requirements_txt,
    extract_dependencies_from_uv_lock,
    extract_skill_dependencies,
)
from myrm_agent_harness.backends.skills.scanning.osv_scanner import (
    parse_osv_severity,
    query_osv_batch,
)
from myrm_agent_harness.backends.skills.scanning.package_audit import (
    PackageAuditFinding,
    audit_package_json,
    audit_package_manifest_dict,
    audit_skill_directory,
    check_lifecycle_scripts,
)
from myrm_agent_harness.backends.skills.scanning.rescan_engine import (
    AdvisoryAck,
    AdvisoryAckRegistry,
    InstalledSkillRescanEngine,
    SkillRescanResult,
    get_rescan_engine,
)
from myrm_agent_harness.backends.skills.scanning.scanner import (
    ScanFinding,
    ScanResult,
    ScanSeverity,
    SkillTrustRecommendation,
    compute_scan_summary,
    format_scan_report,
    scan_skill_content,
    scan_skill_directory,
)
from myrm_agent_harness.backends.skills.scanning.security_advisories import (
    AdvisoryFinding,
    KnownAdvisory,
    get_known_advisories_catalog,
    match_known_advisories,
)
from myrm_agent_harness.backends.skills.scanning.vuln_cache import (
    VulnCacheEntry,
    VulnScanCache,
    get_vuln_cache,
)
from myrm_agent_harness.backends.skills.scanning.zip_extract import safe_extract_zip

__all__ = [
    "AdvisoryAck",
    "AdvisoryAckRegistry",
    "AdvisoryFinding",
    "AstScanFinding",
    "CacheStats",
    "DeclaredDependency",
    "InstalledSkillRescanEngine",
    "KnownAdvisory",
    "PackageAuditFinding",
    "ScanFinding",
    "ScanResult",
    "ScanResultCache",
    "ScanSeverity",
    "SkillRescanResult",
    "SkillTrustRecommendation",
    "VulnCacheEntry",
    "VulnScanCache",
    "analyze_python_ast",
    "audit_package_json",
    "audit_package_manifest_dict",
    "audit_skill_directory",
    "check_lifecycle_scripts",
    "compute_scan_summary",
    "extract_dependencies_from_bun_lock",
    "extract_dependencies_from_files",
    "extract_dependencies_from_package_json",
    "extract_dependencies_from_package_lock_json",
    "extract_dependencies_from_pyproject_toml",
    "extract_dependencies_from_requirements_txt",
    "extract_dependencies_from_uv_lock",
    "extract_skill_dependencies",
    "format_scan_report",
    "get_known_advisories_catalog",
    "get_rescan_engine",
    "get_scan_cache",
    "get_vuln_cache",
    "match_known_advisories",
    "parse_osv_severity",
    "query_osv_batch",
    "safe_extract_zip",
    "scan_skill_content",
    "scan_skill_directory",
]
