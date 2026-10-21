"""
[INPUT]: Raw logs, stack traces, and configuration strings containing potential sensitive secrets.
[OUTPUT]: Fully sanitized strings with zero secret leakage and structured RedactionAuditRecord logs.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/sanitized_debug_dump/redactor.py
"""

import re
from typing import Dict, List, Tuple

from .models import RedactionAuditRecord, RedactionRuleType


class ZeroLeakRedactor:
    """
    Physical-grade regex redaction pipeline that scrubs API keys, bearer tokens,
    absolute filesystem paths, passwords, emails, and IP addresses before diagnostic export.
    """

    _PATTERNS: List[Tuple[RedactionRuleType, re.Pattern[str], str]] = [
        (
            RedactionRuleType.API_KEY,
            re.compile(r"sk-(?:ant-)?[a-zA-Z0-9_-]{20,}|gh[pousr]_[a-zA-Z0-9]{36}", re.IGNORECASE),
            "[REDACTED_API_KEY]",
        ),
        (
            RedactionRuleType.BEARER_TOKEN,
            re.compile(r"Bearer\s+[a-zA-Z0-9_.-]{20,}", re.IGNORECASE),
            "Bearer [REDACTED_TOKEN]",
        ),
        (
            RedactionRuleType.PASSWORD_OR_SECRET,
            re.compile(r"(?i)(password|passwd|api_key|secret|token)\s*[:=]\s*['\"]?([^\s'\",;]+)['\"]?"),
            r"\1=[REDACTED_SECRET]",
        ),
        (
            RedactionRuleType.FILE_SYSTEM_PATH,
            re.compile(r"/(?:Users|home)/[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*"),
            "[USER_WORKSPACE]/path",
        ),
        (
            RedactionRuleType.EMAIL_ADDRESS,
            re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
            "[REDACTED_EMAIL]",
        ),
        (
            RedactionRuleType.IP_ADDRESS,
            re.compile(r"\b(?!127\.0\.0\.1)(?!0\.0\.0\.0)(?:\d{1,3}\.){3}\d{1,3}\b"),
            "[REDACTED_IP]",
        ),
    ]

    def sanitize(self, raw_text: str) -> Tuple[str, List[RedactionAuditRecord]]:
        text = raw_text or ""
        audit_counts: Dict[RedactionRuleType, int] = {}
        placeholders: Dict[RedactionRuleType, str] = {}

        for rule_type, pattern, replacement in self._PATTERNS:
            matches = pattern.findall(text)
            if matches:
                audit_counts[rule_type] = audit_counts.get(rule_type, 0) + len(matches)
                placeholders[rule_type] = replacement
                text = pattern.sub(replacement, text)

        audits: List[RedactionAuditRecord] = [
            RedactionAuditRecord(
                rule_type=rule,
                masked_placeholder=placeholders[rule],
                occurrences_count=cnt,
            )
            for rule, cnt in audit_counts.items()
        ]

        return text, audits

    def sanitize_lines(self, lines: List[str]) -> Tuple[List[str], List[RedactionAuditRecord], int]:
        sanitized_lines: List[str] = []
        total_counts: Dict[RedactionRuleType, int] = {}
        placeholders: Dict[RedactionRuleType, str] = {}
        total_redacted = 0

        for line in lines:
            s_line, audits = self.sanitize(line)
            sanitized_lines.append(s_line)
            for a in audits:
                total_counts[a.rule_type] = total_counts.get(a.rule_type, 0) + a.occurrences_count
                placeholders[a.rule_type] = a.masked_placeholder
                total_redacted += a.occurrences_count

        combined_audits = [
            RedactionAuditRecord(
                rule_type=rule,
                masked_placeholder=placeholders[rule],
                occurrences_count=cnt,
            )
            for rule, cnt in total_counts.items()
        ]

        return sanitized_lines, combined_audits, total_redacted
