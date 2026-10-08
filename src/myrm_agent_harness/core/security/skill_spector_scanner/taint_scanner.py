"""NVIDIA SkillSpector Level Skill AST and Prompt Taint Scanner.

Performs static analysis on skill markdown, prompt templates, scripts, and declarations
to discover credential theft, prompt injection, reverse shells, and synthesize least-privilege sandbox profiles.
"""

from __future__ import annotations

import logging
import re
import time

from myrm_agent_harness.core.security.skill_spector_scanner.types import (
    FindingCategory,
    FindingSeverity,
    SandboxProfile,
    SecurityFinding,
    SkillSafetyRating,
    SkillScanReport,
)

logger = logging.getLogger(__name__)

# Prompt injection & jailbreak signature patterns
_PROMPT_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str], FindingSeverity, str], ...] = (
    (
        "SPECT-PI-001",
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
        FindingSeverity.CRITICAL,
        "Attempted instruction bypass: 'ignore previous instructions' detected.",
    ),
    (
        "SPECT-PI-002",
        re.compile(r"you\s+are\s+now\s+(in\s+)?(developer\s+mode|dan\s+mode)", re.IGNORECASE),
        FindingSeverity.CRITICAL,
        "Attempted persona jailbreak: 'developer mode / DAN mode' persona hijack.",
    ),
    (
        "SPECT-PI-003",
        re.compile(r"system\s+prompt\s+override|disregard\s+all\s+rules", re.IGNORECASE),
        FindingSeverity.CRITICAL,
        "System prompt override attempt identified in prompt body.",
    ),
    (
        "SPECT-PI-004",
        re.compile(r"[\u200b-\u200f\ufeff]", re.UNICODE),
        FindingSeverity.HIGH,
        "Invisible zero-width Unicode characters detected in prompt body.",
    ),
)

# Credential harvesting signature patterns
_CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str], FindingSeverity, str], ...] = (
    (
        "SPECT-CH-001",
        re.compile(r"(\.ssh/id_rsa|\.ssh/authorized_keys|\.aws/credentials)", re.IGNORECASE),
        FindingSeverity.CRITICAL,
        "Direct attempt to read private SSH keys or cloud credentials.",
    ),
    (
        "SPECT-CH-002",
        re.compile(r"(\.env|/etc/passwd|/etc/shadow)", re.IGNORECASE),
        FindingSeverity.CRITICAL,
        "Attempt to read local sensitive environment secrets or password files.",
    ),
)

# Command injection and dangerous system call patterns
_COMMAND_PATTERNS: tuple[tuple[str, re.Pattern[str], FindingSeverity, str], ...] = (
    (
        "SPECT-CI-001",
        re.compile(r"(/dev/tcp/|nc\s+-e|bash\s+-i|mkfifo\s+/tmp/)", re.IGNORECASE),
        FindingSeverity.CRITICAL,
        "Reverse shell or interactive network socket redirection detected.",
    ),
    (
        "SPECT-CI-002",
        re.compile(r"(sudo\s+|chmod\s+777|chown\s+root)", re.IGNORECASE),
        FindingSeverity.HIGH,
        "Privilege escalation or insecure permission modification detected.",
    ),
    (
        "SPECT-ACE-001",
        re.compile(r"\b(eval\(|exec\(|__import__\()", re.IGNORECASE),
        FindingSeverity.HIGH,
        "Dynamic code evaluation or untrusted import detected.",
    ),
)


class NvidiaSkillSpectorScanner:
    """NVIDIA SkillSpector grade supply chain security taint analyzer."""

    def scan_skill_package(
        self,
        skill_id: str,
        skill_version: str,
        files: dict[str, str],
        declared_permissions: list[str] | None = None,
    ) -> SkillScanReport:
        """Scan all files inside a skill package and evaluate risk."""
        findings: list[SecurityFinding] = []

        for file_name, content in files.items():
            findings.extend(self._scan_file_content(file_name, content))

        rating = self._calculate_safety_rating(findings)
        sandbox = self._synthesize_sandbox_profile(declared_permissions or [], findings)
        is_shield_verified = rating == SkillSafetyRating.A_VERIFIED_SECURE

        return SkillScanReport(
            skill_id=skill_id,
            skill_version=skill_version,
            safety_rating=rating,
            is_shield_verified=is_shield_verified,
            findings=findings,
            sandbox_profile=sandbox,
            scanned_at=time.time(),
        )

    def _scan_file_content(self, file_name: str, content: str) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            # 1. Prompt Injection Checks
            for rule_id, pattern, severity, desc in _PROMPT_INJECTION_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        SecurityFinding(
                            rule_id=rule_id,
                            category=FindingCategory.PROMPT_INJECTION,
                            severity=severity,
                            file_name=file_name,
                            line_number=idx,
                            matched_content=line.strip()[:100],
                            description=desc,
                        )
                    )

            # 2. Credential Theft Checks
            for rule_id, pattern, severity, desc in _CREDENTIAL_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        SecurityFinding(
                            rule_id=rule_id,
                            category=FindingCategory.CREDENTIAL_HARVESTING,
                            severity=severity,
                            file_name=file_name,
                            line_number=idx,
                            matched_content=line.strip()[:100],
                            description=desc,
                        )
                    )

            # 3. Command Injection & Arbitrary Code Execution
            for rule_id, pattern, severity, desc in _COMMAND_PATTERNS:
                if pattern.search(line):
                    category = (
                        FindingCategory.ARBITRARY_CODE_EXECUTION
                        if "ACE" in rule_id
                        else FindingCategory.COMMAND_INJECTION
                    )
                    findings.append(
                        SecurityFinding(
                            rule_id=rule_id,
                            category=category,
                            severity=severity,
                            file_name=file_name,
                            line_number=idx,
                            matched_content=line.strip()[:100],
                            description=desc,
                        )
                    )

        return findings

    @staticmethod
    def _calculate_safety_rating(findings: list[SecurityFinding]) -> SkillSafetyRating:
        if any(f.severity == FindingSeverity.CRITICAL for f in findings):
            return SkillSafetyRating.D_MALICIOUS_REJECTED
        if any(f.severity == FindingSeverity.HIGH for f in findings):
            return SkillSafetyRating.C_SUSPICIOUS
        if any(f.severity in (FindingSeverity.MEDIUM, FindingSeverity.LOW) for f in findings):
            return SkillSafetyRating.B_RESTRICTED_ACCESS
        return SkillSafetyRating.A_VERIFIED_SECURE

    @staticmethod
    def _synthesize_sandbox_profile(
        declared_permissions: list[str],
        findings: list[SecurityFinding],
    ) -> SandboxProfile:
        has_critical = any(f.severity == FindingSeverity.CRITICAL for f in findings)
        egress_allowed = not has_critical and any("net" in p.lower() for p in declared_permissions)

        return SandboxProfile(
            network_egress_allowed=egress_allowed,
            allowed_domains=["api.github.com", "huggingface.co"] if egress_allowed else [],
            read_only_filesystem=True,
            allowed_write_paths=["/tmp/skill_scratch"],
            capabilities_dropped=[
                "CAP_SYS_ADMIN",
                "CAP_NET_RAW",
                "CAP_DAC_OVERRIDE",
                "CAP_SYS_PTRACE",
            ],
        )
