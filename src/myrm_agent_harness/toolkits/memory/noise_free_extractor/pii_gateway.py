"""[POS]: src/myrm_agent_harness/toolkits/memory/noise_free_extractor/pii_gateway.py
[INPUT]: Candidate memory statements to inspect for credit cards, IBANs, national IDs, and secrets.
[OUTPUT]: SanitizedExtractionResult detailing safety clearance, masked text, and PII violations.

Reference: Anthropic Commerce Agents (commerce_common/memory.py:DEFAULT_BLOCKED_PATTERNS).
Enforces strict regex filters preventing sensitive personal identifying info (PII)
such as credit card numbers, IBANs, national IDs, and API tokens from entering persistent memory.
"""

import re
from typing import ClassVar

from .types import PIIViolationDetail, SanitizedExtractionResult


class PIISafetyGateway:
    """Rigorous regex-based screening for extracted memory facts."""

    # Pre-compiled high-confidence PII regex patterns
    _PATTERNS: ClassVar[dict[str, tuple[re.Pattern[str], str]]] = {
        "credit_card": (
            re.compile(
                r"\b(?:\d{4}[-\s]?){3}\d{4}\b|\b\d{15,16}\b",
                re.IGNORECASE,
            ),
            "high",
        ),
        "iban": (
            re.compile(
                r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}(?:[A-Z0-9]?){0,16}\b",
                re.IGNORECASE,
            ),
            "critical",
        ),
        "ssn_us": (
            re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
            "critical",
        ),
        "national_id_cn": (
            re.compile(
                r"\b[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"
            ),
            "critical",
        ),
        "secret_token_key": (
            re.compile(
                r"\b(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|bearer\s+[A-Za-z0-9._~+/-]{30,})\b",
                re.IGNORECASE,
            ),
            "critical",
        ),
        "plaintext_credential": (
            re.compile(
                r"\b(?:password|passwd|secret)\s*[:=]\s*[^\s,;]{6,}\b",
                re.IGNORECASE,
            ),
            "critical",
        ),
    }

    def __init__(self, mask_instead_of_reject: bool = False) -> None:
        self.mask_instead_of_reject = mask_instead_of_reject

    @classmethod
    def luhn_validate(cls, card_number: str) -> bool:
        """Optional Luhn checksum validation for digits-only strings."""
        digits = [int(c) for c in card_number if c.isdigit()]
        if len(digits) < 13 or len(digits) > 19:
            return False
        total = 0
        reverse_digits = digits[::-1]
        for idx, digit in enumerate(reverse_digits):
            if idx % 2 == 1:
                doubled = digit * 2
                total += doubled - 9 if doubled > 9 else doubled
            else:
                total += digit
        return total % 10 == 0

    def inspect(self, statement: str) -> SanitizedExtractionResult:
        """Inspect statement against all blocked PII patterns."""
        violations: list[PIIViolationDetail] = []
        sanitized = statement

        for rule_name, (pattern, severity) in self._PATTERNS.items():
            matches = list(pattern.finditer(statement))
            if not matches:
                continue

            for match in matches:
                matched_str = match.group(0)

                # For credit card rule, double-check length or Luhn to minimize false positives
                if rule_name == "credit_card":
                    clean_digits = re.sub(r"\D", "", matched_str)
                    if not self.luhn_validate(clean_digits):
                        continue

                # Mask snippet for auditing
                if len(matched_str) > 6:
                    masked = (
                        matched_str[:2] + "*" * (len(matched_str) - 4) + matched_str[-2:]
                    )
                else:
                    masked = "***"

                violations.append(
                    PIIViolationDetail(
                        rule_name=rule_name,
                        snippet_masked=masked,
                        severity=severity,  # type: ignore[arg-type]
                    )
                )

                if self.mask_instead_of_reject:
                    sanitized = pattern.sub(f"[{rule_name}_REDACTED]", sanitized)

        is_clean = len(violations) == 0
        return SanitizedExtractionResult(
            is_clean=is_clean,
            sanitized_text=sanitized if self.mask_instead_of_reject else statement,
            violations=violations,
        )

    def is_safe_for_storage(self, statement: str) -> bool:
        """Fast boolean check for storage safety."""
        return self.inspect(statement).is_clean
