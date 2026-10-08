"""
[POS] src/myrm_agent_harness/core/security/execution_approval_sanitizer/redaction_engine.py
[INPUT] re, types, pattern_rules
[OUTPUT] ExecutionApprovalSecretRedactionEngine
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re

from .pattern_rules import (
    DEFAULT_SECRET_RULES,
    SecretPatternRule,
    calculate_shannon_entropy,
    is_whitelisted_token,
)
from .types import RedactionFinding, SanitizationResult, SecretType

logger = logging.getLogger(__name__)

_GENERIC_KEY_VALUE_REGEX = re.compile(
    r"""(?i)\b(?:api[_\-]?key|secret|token|password|auth_token)\s*[:=]\s*(?:["']([^"']{16,})["']|([^\s"';]{16,}))"""
)


class ExecutionApprovalSecretRedactionEngine:
    """Detects and masks sensitive credentials in execution approval prompts and commands."""

    def __init__(
        self, custom_rules: tuple[SecretPatternRule, ...] | None = None
    ) -> None:
        self._rules = custom_rules or DEFAULT_SECRET_RULES

    def sanitize_text(self, raw_text: str) -> SanitizationResult:
        """Scan and replace sensitive credential strings with safe redaction placeholders."""
        if not raw_text:
            return SanitizationResult(
                sanitized_text="",
                redactions_count=0,
                detected_secret_types=(),
                findings=(),
                badge_summary="🛡️ 安全核身：未检测到敏感明文凭据",
            )

        sanitized = raw_text
        findings: list[RedactionFinding] = []
        detected_types: set[SecretType] = set()

        # 1. Specialized pattern rules
        for rule in self._rules:
            matches = list(rule.compiled_regex.finditer(sanitized))
            if not matches:
                continue

            for match in matches:
                matched_str = match.group(0)
                # Check whitelist (Git SHA, UUID)
                if is_whitelisted_token(matched_str):
                    continue

                preview = (
                    matched_str[:4] + "..." + matched_str[-3:]
                    if len(matched_str) > 10
                    else "***"
                )

                # Specialized URI password replacement vs direct replacement
                if rule.secret_type == SecretType.DATABASE_PASSWORD:
                    # Uses capture groups: \1[REDACTED:DB_PASSWORD]\3
                    placeholder = rule.compiled_regex.sub(rule.placeholder_template, matched_str)
                elif rule.secret_type == SecretType.BEARER_TOKEN:
                    placeholder = rule.placeholder_template
                else:
                    placeholder = rule.placeholder_template

                finding = RedactionFinding(
                    secret_type=rule.secret_type,
                    start_index=match.start(),
                    end_index=match.end(),
                    matched_preview=preview,
                    placeholder=placeholder,
                )
                findings.append(finding)
                detected_types.add(rule.secret_type)

            # Apply replacement to text
            if rule.secret_type == SecretType.DATABASE_PASSWORD:
                sanitized = rule.compiled_regex.sub(rule.placeholder_template, sanitized)
            else:
                sanitized = rule.compiled_regex.sub(rule.placeholder_template, sanitized)

        # 2. Generic high-entropy key-value assignment check
        generic_matches = list(_GENERIC_KEY_VALUE_REGEX.finditer(sanitized))
        for g_match in generic_matches:
            val = g_match.group(1) if g_match.group(1) is not None else g_match.group(2)
            group_idx = 1 if g_match.group(1) is not None else 2
            if not val or "[REDACTED:" in val:
                continue
            if is_whitelisted_token(val):
                continue
            entropy = calculate_shannon_entropy(val)
            if entropy >= 3.6:  # High-entropy threshold
                preview = val[:3] + "..." + val[-2:] if len(val) > 8 else "***"
                placeholder = "[REDACTED:HIGH_ENTROPY_SECRET]"
                findings.append(
                    RedactionFinding(
                        secret_type=SecretType.GENERIC_HIGH_ENTROPY_SECRET,
                        start_index=g_match.start(group_idx),
                        end_index=g_match.end(group_idx),
                        matched_preview=preview,
                        placeholder=placeholder,
                    )
                )
                detected_types.add(SecretType.GENERIC_HIGH_ENTROPY_SECRET)
                # Replace value part in assignment
                prefix = sanitized[: g_match.start(group_idx)]
                suffix = sanitized[g_match.end(group_idx) :]
                sanitized = prefix + placeholder + suffix

        count = len(findings)
        if count == 0:
            badge = "🛡️ 安全核身：未检测到敏感明文凭据"
        else:
            types_str = ", ".join(sorted(t.value for t in detected_types))
            badge = f"🛡️ 已自动脱敏 {count} 处敏感凭据（类型: {types_str}），沙箱执行时将安全注入"

        return SanitizationResult(
            sanitized_text=sanitized,
            redactions_count=count,
            detected_secret_types=tuple(sorted(detected_types, key=lambda x: x.value)),
            findings=tuple(findings),
            badge_summary=badge,
        )
