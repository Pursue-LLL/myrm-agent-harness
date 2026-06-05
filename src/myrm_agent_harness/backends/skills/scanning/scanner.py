from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path

from myrm_agent_harness.backends.skills.scanning.ast_analyzer import AstScanFinding
from myrm_agent_harness.backends.skills.types import SecurityScanSummary

"""Skill content security scanner.

[INPUT]
- scanning.patterns::ALL_PATTERN_GROUPS (POS: Skill security scanner pattern definitions.)

[OUTPUT]
- ScanSeverity: scan finding severity enum
- ScanFinding: single scan finding
- ScanResult: complete scan result with SkillTrust recommendation
- SkillTrustRecommendation: recommended trust level based on findings
- scan_skill_content(): scan skill content for security threats
- compute_scan_summary(): generate SecurityScanSummary from ScanResult
- format_scan_report(): generate human-readable scan report for Agent feedback

[POS]
Skill content security scanner. Part of the framework's defense-in-depth.
Trust attenuation is the hard limit (restricts tools), scanner is the
soft detection layer (warns users and recommends trust levels).

Detects 26 threat categories (108 patterns): prompt injection, command injection,
credential exposure, data exfiltration, file system access,
process operations, network access, screen/input capture,
memory/config snooping, code injection, privilege escalation,
environment manipulation, reflection/metaprogramming,
deserialization attacks, log/audit tampering, scheduled task injection,
container escape, memory manipulation, DNS tunneling,
supply chain attacks, obfuscation, destructive operations,
persistence mechanisms, path traversal, crypto mining,
reverse shell, invisible unicode.

Scan results influence SkillTrust level via SkillTrustRecommendation:
- Critical findings → REJECT
- High findings → UNTRUSTED
- Medium/Low findings → INSTALLED (normal install with attenuation)
- No findings → TRUSTED
"""


logger = logging.getLogger(__name__)


class ScanSeverity(IntEnum):
    """Scan finding severity level."""

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class SkillTrustRecommendation(StrEnum):
    """Recommended trust level based on scan findings.

    Maps to the existing SkillTrust enum in attenuator:
    - TRUSTED: no findings, full tool access
    - INSTALLED: medium/low findings, trust attenuation active
    - UNTRUSTED: high/critical findings, requires user confirmation
    - REJECT: critical findings, installation should be blocked
    """

    TRUSTED = "trusted"
    INSTALLED = "installed"
    UNTRUSTED = "untrusted"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class ScanFinding:
    """A single security finding from the scanner."""

    threat_type: str
    severity: ScanSeverity
    description: str
    line_number: int | None = None


@dataclass
class ScanResult:
    """Complete scan result for a skill."""

    skill_name: str
    findings: list[ScanFinding] = field(default_factory=list)
    ast_findings: list[AstScanFinding] = field(default_factory=list)
    scan_duration_ms: float = 0.0

    @property
    def is_clean(self) -> bool:
        return len(self.findings) == 0 and len(self.ast_findings) == 0

    @property
    def max_severity(self) -> ScanSeverity | None:
        all_severities = [f.severity for f in self.findings]
        if self.ast_findings:
            ast_sev_map = {
                "critical": ScanSeverity.CRITICAL,
                "high": ScanSeverity.HIGH,
                "medium": ScanSeverity.MEDIUM,
                "low": ScanSeverity.LOW,
                "info": ScanSeverity.INFO,
            }
            all_severities.extend(ast_sev_map.get(af.severity, ScanSeverity.INFO) for af in self.ast_findings)
        if not all_severities:
            return None
        return max(all_severities)

    @property
    def trust_recommendation(self) -> SkillTrustRecommendation:
        """Recommend a trust level based on the worst finding."""
        severity = self.max_severity
        if severity is None:
            return SkillTrustRecommendation.TRUSTED
        if severity >= ScanSeverity.CRITICAL:
            return SkillTrustRecommendation.REJECT
        if severity >= ScanSeverity.HIGH:
            return SkillTrustRecommendation.UNTRUSTED
        if severity >= ScanSeverity.MEDIUM:
            return SkillTrustRecommendation.INSTALLED
        return SkillTrustRecommendation.TRUSTED

    @property
    def summary(self) -> str:
        if self.is_clean:
            return f"Skill '{self.skill_name}': clean"
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.threat_type] = counts.get(f.threat_type, 0) + 1
        for af in self.ast_findings:
            counts[af.threat_type] = counts.get(af.threat_type, 0) + 1
        parts = [f"{t}({c})" for t, c in sorted(counts.items())]
        total = len(self.findings) + len(self.ast_findings)
        return (
            f"Skill '{self.skill_name}': {total} finding(s) — {', '.join(parts)} [trust: {self.trust_recommendation}]"
        )


# Invisible Unicode categories that should not appear in skill content
_SUSPICIOUS_UNICODE_CATEGORIES = frozenset(
    {
        "Cf",  # Format characters (zero-width spaces, directional overrides)
        "Co",  # Private use characters
        "Cn",  # Unassigned characters
    }
)

# Specific dangerous codepoints
_DANGEROUS_CODEPOINTS = frozenset(
    {
        0x200B,  # Zero-width space
        0x200C,  # Zero-width non-joiner
        0x200D,  # Zero-width joiner
        0x200E,  # Left-to-right mark
        0x200F,  # Right-to-left mark
        0x202A,  # Left-to-right embedding
        0x202B,  # Right-to-left embedding
        0x202C,  # Pop directional formatting
        0x202D,  # Left-to-right override
        0x202E,  # Right-to-left override
        0x2060,  # Word joiner
        0x2061,  # Function application
        0x2062,  # Invisible times
        0x2063,  # Invisible separator
        0x2064,  # Invisible plus
        0xFEFF,  # Zero-width no-break space (BOM)
        0xFFF9,  # Interlinear annotation anchor
        0xFFFA,  # Interlinear annotation separator
        0xFFFB,  # Interlinear annotation terminator
    }
)


def _get_pattern_groups() -> list[tuple[str, list[tuple[re.Pattern[str], str, ScanSeverity]]]]:
    """Lazy import to break circular dependency (patterns imports ScanSeverity from here)."""
    from myrm_agent_harness.backends.skills.scanning.patterns import ALL_PATTERN_GROUPS

    return ALL_PATTERN_GROUPS


def scan_skill_content(
    skill_name: str,
    content: str,
    *,
    file_extension: str = "",
) -> ScanResult:
    """Scan skill content for security threats.

    This is a soft detection layer — findings are warnings, not blockers.
    The trust attenuation system provides the hard security boundary.

    Runs three analysis passes:
    1. Regex pattern matching (26 categories, 108 patterns)
    2. Invisible Unicode detection
    3. Python AST analysis (for .py files)

    Args:
        skill_name: Skill identifier for the result
        content: Text content to scan (SKILL.md, .py, .sh, or any text file)
        file_extension: File extension hint (e.g. ".py") for AST analysis

    Returns:
        ScanResult with all findings (empty if clean)
    """
    start_time = time.monotonic()
    result = ScanResult(skill_name=skill_name)
    pattern_groups = _get_pattern_groups()

    lines = content.split("\n")

    for line_num, line in enumerate(lines, start=1):
        for threat_type, patterns in pattern_groups:
            for pattern, description, severity in patterns:
                if pattern.search(line):
                    result.findings.append(
                        ScanFinding(
                            threat_type=threat_type,
                            severity=severity,
                            description=description,
                            line_number=line_num,
                        )
                    )

    _scan_invisible_unicode(content, result)

    # AST analysis for Python files
    if file_extension == ".py" or (not file_extension and _looks_like_python(content)):
        from myrm_agent_harness.backends.skills.scanning.ast_analyzer import analyze_python_ast

        ast_findings = analyze_python_ast(content, skill_name)
        result.ast_findings.extend(ast_findings)

    result.scan_duration_ms = (time.monotonic() - start_time) * 1000

    if not result.is_clean:
        if result.trust_recommendation in (SkillTrustRecommendation.UNTRUSTED, SkillTrustRecommendation.REJECT):
            logger.warning("Security scan: %s", result.summary)
        else:
            logger.info("Security scan: %s", result.summary)

    return result


def _scan_invisible_unicode(content: str, result: ScanResult) -> None:
    """Detect invisible/suspicious Unicode characters in content."""
    for line_num, line in enumerate(content.split("\n"), start=1):
        for i, char in enumerate(line):
            cp = ord(char)
            if cp in _DANGEROUS_CODEPOINTS:
                name = unicodedata.name(char, f"U+{cp:04X}")
                result.findings.append(
                    ScanFinding(
                        threat_type="invisible_unicode",
                        severity=ScanSeverity.HIGH,
                        description=f"Invisible Unicode: {name} (U+{cp:04X}) at column {i + 1}",
                        line_number=line_num,
                    )
                )
            elif unicodedata.category(char) in _SUSPICIOUS_UNICODE_CATEGORIES and cp > 0x7F:
                name = unicodedata.name(char, f"U+{cp:04X}")
                result.findings.append(
                    ScanFinding(
                        threat_type="invisible_unicode",
                        severity=ScanSeverity.MEDIUM,
                        description=f"Suspicious Unicode category ({unicodedata.category(char)}): {name} (U+{cp:04X})",
                        line_number=line_num,
                    )
                )


def _looks_like_python(content: str) -> bool:
    """Heuristic: check if content looks like Python source code."""
    first_lines = content[:500]
    indicators = ("def ", "import ", "from ", "class ", "if __name__")
    return any(indicator in first_lines for indicator in indicators)


# ---------------------------------------------------------------------------
# Multi-file directory scanning
# ---------------------------------------------------------------------------

_MAX_SCAN_FILES = 500
_MAX_FILE_SIZE = 512 * 1024  # 512 KB
_SCAN_TIMEOUT_S = 5.0
_SKIP_DIRS = frozenset({"node_modules", ".git", "__pycache__", ".venv", "venv", ".svn", ".hg"})
_TEXT_EXTENSIONS = frozenset(
    {".py", ".sh", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".js", ".ts"}
)


def scan_skill_directory(
    skill_name: str,
    skill_dir: str | Path,
) -> ScanResult:
    """Scan all files in a skill directory for security threats.

    Performs multi-file scanning with safety limits:
    - MAX_SCAN_FILES: 500 files
    - MAX_FILE_SIZE: 512 KB per file
    - SCAN_TIMEOUT: 5 seconds

    Also audits any package.json files found.

    Args:
        skill_name: Skill identifier
        skill_dir: Path to the skill directory

    Returns:
        Combined ScanResult from all files
    """
    from myrm_agent_harness.backends.skills.scanning.package_audit import audit_skill_directory

    start_time = time.monotonic()
    root = Path(skill_dir)
    combined = ScanResult(skill_name=skill_name)

    if not root.is_dir():
        combined.scan_duration_ms = (time.monotonic() - start_time) * 1000
        return combined

    files_scanned = 0
    for file_path in _walk_text_files(root):
        if files_scanned >= _MAX_SCAN_FILES:
            break
        elapsed = time.monotonic() - start_time
        if elapsed > _SCAN_TIMEOUT_S:
            logger.warning("Scan timeout: scanned %d files in %.1fs", files_scanned, elapsed)
            break

        relative = str(file_path.relative_to(root))
        ext = file_path.suffix.lower()

        try:
            stat = file_path.stat()
            if stat.st_size > _MAX_FILE_SIZE or stat.st_size == 0:
                continue
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        files_scanned += 1
        file_result = scan_skill_content(f"{skill_name}/{relative}", content, file_extension=ext)
        combined.findings.extend(file_result.findings)
        combined.ast_findings.extend(file_result.ast_findings)

    # Package.json audit
    pkg_findings = audit_skill_directory(root)
    for pf in pkg_findings:
        combined.findings.append(
            ScanFinding(
                threat_type=pf.threat_type,
                severity=ScanSeverity.HIGH if pf.severity == "high" else ScanSeverity.MEDIUM,
                description=pf.description,
            )
        )

    combined.scan_duration_ms = (time.monotonic() - start_time) * 1000

    if not combined.is_clean:
        logger.warning("Directory scan: %s", combined.summary)

    return combined


def _walk_text_files(root: Path):
    """Walk text files in a directory, skipping ignored directories."""
    queue: list[Path] = [root]

    while queue:
        current = queue.pop(0)
        try:
            entries = sorted(current.iterdir())
        except PermissionError:
            continue

        for entry in entries:
            if entry.name.startswith(".") and entry.name not in {".env", ".gitignore"}:
                continue
            if entry.name in _SKIP_DIRS:
                continue
            if entry.is_symlink():
                continue
            if entry.is_file():
                ext = entry.suffix.lower()
                if ext in _TEXT_EXTENSIONS or entry.name == "SKILL.md":
                    yield entry
            elif entry.is_dir():
                queue.append(entry)


_SEVERITY_DEDUCTIONS: dict[ScanSeverity, int] = {
    ScanSeverity.CRITICAL: 25,
    ScanSeverity.HIGH: 12,
    ScanSeverity.MEDIUM: 5,
    ScanSeverity.LOW: 2,
    ScanSeverity.INFO: 0,
}

_TRUST_SCORE_BANDS: dict[SkillTrustRecommendation, tuple[int, int]] = {
    SkillTrustRecommendation.TRUSTED: (100, 100),
    SkillTrustRecommendation.INSTALLED: (50, 99),
    SkillTrustRecommendation.UNTRUSTED: (25, 49),
    SkillTrustRecommendation.REJECT: (0, 24),
}


_AST_SEVERITY_MAP: dict[str, ScanSeverity] = {
    "critical": ScanSeverity.CRITICAL,
    "high": ScanSeverity.HIGH,
    "medium": ScanSeverity.MEDIUM,
    "low": ScanSeverity.LOW,
    "info": ScanSeverity.INFO,
}


def compute_scan_summary(result: ScanResult) -> SecurityScanSummary:
    """Generate a SecurityScanSummary from a ScanResult.

    Score is derived consistently with trust_recommendation:
    trust_recommendation determines the band, deductions refine within it.
    Includes both regex findings and AST findings.
    """
    from myrm_agent_harness.backends.skills.types import SecurityFindingDetail, SecurityScanSummary

    trust = result.trust_recommendation

    finding_counts: dict[str, int] = {}
    raw_deduction = 0
    details: list[SecurityFindingDetail] = []

    for f in result.findings:
        sev_name = f.severity.name.lower()
        finding_counts[sev_name] = finding_counts.get(sev_name, 0) + 1
        raw_deduction += _SEVERITY_DEDUCTIONS.get(f.severity, 0)
        details.append(
            SecurityFindingDetail(
                threat_type=f.threat_type,
                severity=sev_name,
                description=f.description,
            )
        )

    for af in result.ast_findings:
        sev = _AST_SEVERITY_MAP.get(af.severity, ScanSeverity.INFO)
        sev_name = sev.name.lower()
        finding_counts[sev_name] = finding_counts.get(sev_name, 0) + 1
        raw_deduction += _SEVERITY_DEDUCTIONS.get(sev, 0)
        details.append(
            SecurityFindingDetail(
                threat_type=af.threat_type,
                severity=sev_name,
                description=af.description,
            )
        )

    raw_score = max(0, 100 - raw_deduction)
    band_min, band_max = _TRUST_SCORE_BANDS[trust]
    score = max(band_min, min(band_max, raw_score))

    return SecurityScanSummary(
        score=score,
        trust_recommendation=trust.value,
        finding_counts=finding_counts,
        total_findings=len(result.findings) + len(result.ast_findings),
        findings=tuple(details),
    )


def format_scan_report(result: ScanResult) -> str:
    """Generate a human-readable scan report for Agent self-correction.

    The report is designed to be included in tool output so the Agent
    can understand what was flagged and fix the content before retrying.

    Args:
        result: Scan result to format

    Returns:
        Formatted report string
    """
    if result.is_clean:
        return f"Security scan passed: skill '{result.skill_name}' is clean."

    total = len(result.findings) + len(result.ast_findings)
    lines = [
        f"Security scan for '{result.skill_name}': {total} finding(s)",
        f"Trust recommendation: {result.trust_recommendation.value}",
    ]
    if result.scan_duration_ms > 0:
        lines.append(f"Scan duration: {result.scan_duration_ms:.1f}ms")
    lines.append("")

    # Regex findings grouped by severity
    by_severity: dict[ScanSeverity, list[ScanFinding]] = {}
    for finding in result.findings:
        by_severity.setdefault(finding.severity, []).append(finding)

    for severity in sorted(by_severity, reverse=True):
        findings = by_severity[severity]
        lines.append(f"[{severity.name}] ({len(findings)} finding(s)):")
        for f in findings:
            loc = f"line {f.line_number}" if f.line_number else "unknown"
            lines.append(f"  - {f.description} ({loc})")
        lines.append("")

    # AST findings
    if result.ast_findings:
        ast_by_severity: dict[str, list[AstScanFinding]] = {}
        for af in result.ast_findings:
            ast_by_severity.setdefault(af.severity, []).append(af)

        lines.append(f"[AST Analysis] ({len(result.ast_findings)} finding(s)):")
        for sev in ("critical", "high", "medium", "low", "info"):
            findings = ast_by_severity.get(sev, [])
            for af in findings:
                loc = f"line {af.line_number}" if af.line_number else "unknown"
                lines.append(f"  - [{sev.upper()}] {af.description} ({loc})")
        lines.append("")

    if result.trust_recommendation == SkillTrustRecommendation.REJECT:
        lines.append("ACTION REQUIRED: Remove the flagged content and retry.")
    elif result.trust_recommendation == SkillTrustRecommendation.UNTRUSTED:
        lines.append("WARNING: Skill saved with restricted trust level. Review flagged lines.")

    return "\n".join(lines)
