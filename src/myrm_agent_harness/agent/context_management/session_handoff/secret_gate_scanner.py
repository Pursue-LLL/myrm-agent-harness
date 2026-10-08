"""Dual-tier secret gate scanner: storage masking placeholders and pre-publish scan blocking."""

from __future__ import annotations

import re
from typing import Dict, List, Pattern, Tuple

from .session_handoff_types import SecretFinding, SecretGateScanResult, SecretSeverity


class SecretGateScanner:
    """Provides non-destructive storage placeholder masking and pre-publish gate scanning."""

    SECRET_PATTERNS: List[Tuple[str, Pattern[str], SecretSeverity]] = [
        (
            "OPENAI_API_KEY",
            re.compile(r"\b(sk-[a-zA-Z0-9_\-]{20,})\b"),
            SecretSeverity.CRITICAL,
        ),
        (
            "AWS_ACCESS_KEY_ID",
            re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
            SecretSeverity.HIGH,
        ),
        (
            "GITHUB_TOKEN",
            re.compile(r"\b(ghp_[a-zA-Z0-9]{20,})\b"),
            SecretSeverity.CRITICAL,
        ),
        (
            "GENERIC_BEARER",
            re.compile(r"(?i)\b(bearer\s+[a-zA-Z0-9\-_\.]{20,})\b"),
            SecretSeverity.HIGH,
        ),
        (
            "GENERIC_PASSWORD",
            re.compile(r"(?i)(password\s*[:=]\s*['\"][^'\"]{6,}['\"])"),
            SecretSeverity.MEDIUM,
        ),
    ]

    def mask_for_storage(self, text: str) -> str:
        """Tier 1: Replace raw secrets with structured non-destructive placeholders."""
        masked_text = text
        for rule_name, pattern, _ in self.SECRET_PATTERNS:
            placeholder = f"<REDACTED_SECRET:{rule_name}>"
            masked_text = pattern.sub(placeholder, masked_text)
        return masked_text

    def scan_for_release_gate(
        self,
        texts: List[str],
        env_vars: Dict[str, str],
        block_on_critical: bool = True,
    ) -> SecretGateScanResult:
        """Tier 2: Deep scan before public handoff/sharing. Blocks if unmasked secrets exist."""
        findings: List[SecretFinding] = []

        # Scan text blocks
        for idx, text in enumerate(texts):
            for rule_name, pattern, severity in self.SECRET_PATTERNS:
                matches = pattern.finditer(text)
                for match in matches:
                    snippet = match.group(0)
                    findings.append(
                        SecretFinding(
                            rule_name=rule_name,
                            severity=severity,
                            pattern_matched=snippet[:6] + "..." + snippet[-4:] if len(snippet) > 10 else "***",
                            location_hint=f"text_block_{idx}",
                            masked_placeholder=f"<REDACTED_SECRET:{rule_name}>",
                        )
                    )

        # Scan exported env vars
        for k, v in env_vars.items():
            for rule_name, pattern, severity in self.SECRET_PATTERNS:
                if pattern.search(v) or ("KEY" in k.upper() and len(v) > 10) or ("SECRET" in k.upper() and len(v) > 6):
                    findings.append(
                        SecretFinding(
                            rule_name=rule_name,
                            severity=severity,
                            pattern_matched=f"{k}=***",
                            location_hint=f"env_var:{k}",
                            masked_placeholder=f"<REDACTED_SECRET:{rule_name}>",
                        )
                    )

        critical_count = sum(1 for f in findings if f.severity in (SecretSeverity.CRITICAL, SecretSeverity.HIGH))
        passed = True
        rejection: str | None = None

        if block_on_critical and critical_count > 0:
            passed = False
            rejection = f"Pre-publish secret gate blocked release: {critical_count} critical/high secrets detected."
        elif len(findings) > 0 and block_on_critical:
            passed = False
            rejection = f"Pre-publish secret gate blocked release: {len(findings)} unmasked secrets found."

        return SecretGateScanResult(
            passed=passed,
            findings_count=len(findings),
            critical_findings_count=critical_count,
            findings=findings,
            rejection_reason=rejection,
        )
