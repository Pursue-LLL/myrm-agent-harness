"""Memory privacy boundary gate enforcing exclusion rules, secret detection, and safe redaction.

Serves as the mandatory checkpoint before any observation, facts, or notes are persisted
into permanent memory storage or version-controlled Markdown Wikis.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.privacy_gate.rule_matcher::PathAndExclusionMatcher (POS: Path and content rule matcher for
  memory privacy boundaries.)
- toolkits.memory.privacy_gate.secret_detector::DeterministicSecretDetector (POS: Deterministic
  pattern-based detector for high-risk secrets and credentials.)
- toolkits.memory.privacy_gate.types::MemoryPrivacyConfig, PrivacyBoundaryViolationError,
  PrivacyCheckResult, PrivacySensitivityLevel, PrivacyViolationType, SecretFinding (POS: Type definitions
  and contracts for memory privacy boundary and allowlist gate.)

[OUTPUT]
- MemoryPrivacyBoundaryGate: Pre-commit security boundary gate for agent memory persistence.

[POS]
Memory privacy boundary gate enforcing exclusion rules, secret detection, and safe redaction.
"""

from __future__ import annotations

import logging
from pathlib import Path

from myrm_agent_harness.toolkits.memory.privacy_gate.rule_matcher import PathAndExclusionMatcher
from myrm_agent_harness.toolkits.memory.privacy_gate.secret_detector import DeterministicSecretDetector
from myrm_agent_harness.toolkits.memory.privacy_gate.types import (
    MemoryPrivacyConfig,
    PrivacyBoundaryViolationError,
    PrivacyCheckResult,
    PrivacySensitivityLevel,
    PrivacyViolationType,
    SecretFinding,
)

logger = logging.getLogger(__name__)


class MemoryPrivacyBoundaryGate:
    """Pre-commit security boundary gate for agent memory persistence."""

    def __init__(
        self,
        config: MemoryPrivacyConfig | None = None,
        ignore_file_path: Path | str | None = None,
    ) -> None:
        self.config = config or MemoryPrivacyConfig()
        self.matcher = PathAndExclusionMatcher(
            allow_patterns=self.config.allow_patterns,
            exclude_patterns=self.config.exclude_patterns,
            ignore_file_path=ignore_file_path,
        )
        self.detector = DeterministicSecretDetector()

    def check(self, content: str, source_path: str | None = None) -> PrivacyCheckResult:
        """Inspect candidate memory content and source path for security violations.

        Args:
            content: Textual memory payload to evaluate.
            source_path: Optional file path or origin of the memory.

        Returns:
            PrivacyCheckResult indicating compliance status, findings, and safe redaction.
        """
        findings: list[SecretFinding] = []

        # 1. Path-level exclusion check
        if source_path is not None:
            is_safe, path_reason = self.matcher.check_path(source_path)
            if not is_safe:
                findings.append(
                    SecretFinding(
                        violation_type=PrivacyViolationType.EXCLUDED_PATH,
                        snippet_masked=f"prohibited_source: {path_reason or source_path}",
                        category="Excluded File Path",
                        line_number=1,
                    )
                )

        # 2. Content secret scanning and safe redaction
        redacted_content, content_findings = self.detector.redact(content)
        findings.extend(content_findings)

        # 3. Classify overall sensitivity level
        critical_types = {
            PrivacyViolationType.API_KEY,
            PrivacyViolationType.PRIVATE_KEY,
            PrivacyViolationType.CONNECTION_URI,
            PrivacyViolationType.EXCLUDED_PATH,
        }
        has_critical = any(f.violation_type in critical_types for f in findings)
        has_sensitive = bool(findings) and not has_critical

        if has_critical:
            sensitivity = PrivacySensitivityLevel.CRITICAL_SECRET
        elif has_sensitive:
            sensitivity = PrivacySensitivityLevel.SENSITIVE
        else:
            sensitivity = PrivacySensitivityLevel.PUBLIC

        # 4. Determine pass/fail based on policy mode
        if not findings:
            passed = True
            reason = None
        elif self.config.strict_mode:
            passed = False
            reason = f"Strict mode rejected memory: {len(findings)} sensitive items detected."
        elif self.config.block_on_critical and has_critical:
            passed = False
            first_crit = next(f for f in findings if f.violation_type in critical_types)
            reason = (
                f"Critical secret detected ({first_crit.category} at line {first_crit.line_number}). "
                "Hard veto enforced to prevent credential leakage."
            )
        else:
            # Masking allowed to proceed
            passed = True
            reason = None

        return PrivacyCheckResult(
            passed=passed,
            sensitivity_level=sensitivity,
            findings=findings,
            redacted_content=redacted_content,
            violation_reason=reason,
        )

    def sanitize(self, content: str, source_path: str | None = None) -> str:
        """Sanitize content by redacting secrets without raising hard errors.

        Raises PrivacyBoundaryViolationError only if source_path is explicitly excluded
        and block_on_critical is enabled.
        """
        if source_path is not None and self.config.block_on_critical:
            is_safe, reason = self.matcher.check_path(source_path)
            if not is_safe:
                raise PrivacyBoundaryViolationError(reason or "Excluded source path rejected.")

        redacted, _ = self.detector.redact(content)
        return redacted

    def enforce(self, content: str, source_path: str | None = None) -> str:
        """Enforce privacy boundary; vetoes persistence if violations breach policy.

        Returns:
            Sanitized and redacted text if checks pass.

        Raises:
            PrivacyBoundaryViolationError: If hard veto is triggered.
        """
        result = self.check(content, source_path=source_path)
        if not result.passed:
            logger.warning("Memory privacy boundary veto triggered: %s", result.violation_reason)
            raise PrivacyBoundaryViolationError(
                result.violation_reason or "Memory candidate failed privacy boundary evaluation."
            )
        return result.redacted_content
