"""Static code security auditor and capability conformance scanner for plugins."""

from __future__ import annotations

import re
import time

from .types import (
    AuditFinding,
    CapabilityScope,
    PluginAuditReport,
    PluginManifest,
    PluginSafetyRating,
)

# High-risk patterns mapped to required capability scopes and severity
_RISK_PATTERNS: list[tuple[str, str, str, CapabilityScope, str]] = [
    # (regex_pattern, rule_id, severity, required_scope, description)
    (
        r"\b(eval|exec)\s*\(",
        "SEC-001",
        "CRITICAL",
        CapabilityScope.PROCESS_SPAWN,
        "Dynamic code evaluation (eval/exec) detected.",
    ),
    (
        r"\b(subprocess\.(Popen|run|call)|os\.system|os\.popen)\b",
        "SEC-002",
        "CRITICAL",
        CapabilityScope.PROCESS_SPAWN,
        "Process spawn or shell execution without declared PROCESS_SPAWN scope.",
    ),
    (
        r"\b(requests\.(get|post|put|delete)|httpx\.(get|post|AsyncClient)|urllib\.request)\b",
        "SEC-003",
        "CRITICAL",
        CapabilityScope.NETWORK_EGRESS,
        "Outbound HTTP network call detected without declared NETWORK_EGRESS scope.",
    ),
    (
        r"\bopen\s*\([^)]*['\"][wWaA]\+?['\"]",
        "SEC-004",
        "CRITICAL",
        CapabilityScope.FILESYSTEM_WRITE,
        "File write operation detected without declared FILESYSTEM_WRITE scope.",
    ),
    (
        r"\bos\.(remove|unlink|rmdir)|shutil\.rmtree\b",
        "SEC-005",
        "CRITICAL",
        CapabilityScope.FILESYSTEM_WRITE,
        "Destructive filesystem mutation detected without declared FILESYSTEM_WRITE scope.",
    ),
    (
        r"\bos\.environ(\.get|\[)",
        "SEC-006",
        "WARNING",
        CapabilityScope.ENV_ACCESS,
        "Environment variable access detected.",
    ),
]


class PluginStaticAuditor:
    """Performs static code auditing against plugin manifest capability declarations."""

    def audit_code(
        self,
        manifest: PluginManifest,
        code_files: dict[str, str],
    ) -> PluginAuditReport:
        """Analyze code files against declared capabilities and security rules."""
        findings: list[AuditFinding] = []
        declared_set = set(manifest.declared_scopes)

        for filename, source in code_files.items():
            lines = source.splitlines()
            for line_idx, line in enumerate(lines, start=1):
                # Skip comments
                clean_line = line.strip()
                if clean_line.startswith("#") or clean_line.startswith("//"):
                    continue

                for pattern, rule_id, default_sev, req_scope, desc in _RISK_PATTERNS:
                    if re.search(pattern, clean_line):
                        # If the scope was NOT declared, upgrade severity to CRITICAL
                        if req_scope not in declared_set:
                            severity = "CRITICAL"
                            detail = f"Undeclared capability violation: {desc}"
                        else:
                            severity = "INFO" if default_sev != "CRITICAL" else "WARNING"
                            detail = f"Declared capability usage: {desc}"

                        findings.append(
                            AuditFinding(
                                severity=severity,
                                rule_id=rule_id,
                                description=detail,
                                file_path=filename,
                                line_number=line_idx,
                            )
                        )

        # Calculate final safety rating
        critical_count = sum(1 for f in findings if f.severity == "CRITICAL")
        warning_count = sum(1 for f in findings if f.severity == "WARNING")

        safety_rating: PluginSafetyRating
        is_allowed: bool

        if critical_count > 0:
            safety_rating = PluginSafetyRating.F_UNTRUSTED
            is_allowed = False
        elif warning_count > 2:
            safety_rating = PluginSafetyRating.C_ELEVATED_RISK
            is_allowed = True
        elif len(manifest.declared_scopes) > 3 or warning_count > 0:
            safety_rating = PluginSafetyRating.B_GOOD
            is_allowed = True
        else:
            safety_rating = PluginSafetyRating.A_EXCELLENT
            is_allowed = True

        return PluginAuditReport(
            plugin_id=manifest.plugin_id,
            safety_rating=safety_rating,
            is_install_allowed=is_allowed,
            findings=findings,
            scanned_files_count=len(code_files),
            audit_timestamp=time.time(),
        )
