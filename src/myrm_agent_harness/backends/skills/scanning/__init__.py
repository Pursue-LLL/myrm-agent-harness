"""Skill content security scanning subsystem.

Provides static pattern scanning (26 threat categories, 108 patterns),
Python AST analysis, package.json audit, multi-file directory scanning,
invisible Unicode detection, LLM-based semantic audit, persistent Volume cache
for 20x performance improvement, and secure ZIP extraction with Zip Bomb /
symlink / path traversal defense.
"""

from myrm_agent_harness.backends.skills.scanning.ast_analyzer import AstScanFinding, analyze_python_ast
from myrm_agent_harness.backends.skills.scanning.cache import (
    CacheStats,
    ScanResultCache,
    get_scan_cache,
)
from myrm_agent_harness.backends.skills.scanning.package_audit import (
    PackageAuditFinding,
    audit_package_json,
    audit_skill_directory,
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
from myrm_agent_harness.backends.skills.scanning.zip_extract import safe_extract_zip

__all__ = [
    "AstScanFinding",
    "CacheStats",
    "PackageAuditFinding",
    "ScanFinding",
    "ScanResult",
    "ScanResultCache",
    "ScanSeverity",
    "SkillTrustRecommendation",
    "analyze_python_ast",
    "audit_package_json",
    "audit_skill_directory",
    "compute_scan_summary",
    "format_scan_report",
    "get_scan_cache",
    "safe_extract_zip",
    "scan_skill_content",
    "scan_skill_directory",
]
