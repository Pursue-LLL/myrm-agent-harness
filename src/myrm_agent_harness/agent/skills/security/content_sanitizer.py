"""Content Sanitizer - 技能导出内容脱敏

Scans and redacts sensitive information (API keys, tokens, absolute paths,
credentials, PEM keys, DB connection strings) from skill files before export.
Two-stage design: scan → return structured Diff → user confirms → apply.

Reuses proven patterns from core/security/redact/patterns.py (runtime redactor) to
ensure export-time detection parity with runtime masking. Each rule names the
capture group that holds the secret, so only the secret is replaced and the
surrounding syntax (keys, quotes, flags, URL structure) stays intact.

[INPUT]
- core.security.redact.patterns (POS: Compiled regex patterns and the keyword guard shared with the runtime redactor)

[OUTPUT]
- Redaction: TypedDict — single redaction finding
- SanitizationResult: dataclass — complete scan result
- ContentSanitizer: class — stateless sanitizer
- content_sanitizer: singleton instance

[POS]
Skill export content sanitizer. Detects secrets/paths/credentials in skill
files and provides structured per-line Diff for the frontend preview UI.
"""

import logging
import re
from dataclasses import dataclass
from typing import NamedTuple, TypedDict

from myrm_agent_harness.core.security.redact.patterns import (
    _AUTH_HEADER_RE,
    _CLI_FLAG_RE,
    _DB_CONNSTR_RE,
    _ENV_ASSIGN_LOWER_RE,
    _ENV_ASSIGN_RE,
    _JSON_FIELD_RE,
    _JWT_RE,
    _PREFIX_RE,
    _PRIVATE_KEY_RE,
    _SECRET_HEADER_RE,
    _TELEGRAM_BOT_RE,
    _URL_BARE_TOKEN_RE,
    _URL_QUERY_RE,
    _URL_USERINFO_RE,
    _YAML_ASSIGN_RE,
    _redact_value,
)

logger = logging.getLogger(__name__)

_TOKEN_PREFIX_REASON = "API Key / Token"
_ENV_REASON = "Environment Variable"
_CONFIG_REASON = "Config Secret"
_JSON_REASON = "JSON Secret Field"
_DB_REASON = "Database Credential"
_URL_REASON = "URL Secret Parameter"
_URL_CREDENTIAL_REASON = "URL Credential"
_CLI_REASON = "CLI Secret Flag"
_TELEGRAM_REASON = "Telegram Bot Token"
_AUTH_REASON = "Authorization Header"
_PEM_REASON = "Private Key"
_PATH_REASON = "Absolute Path"

# Absolute paths (macOS/Linux) — supports line-start via (?:^|...) with MULTILINE
_MACOS_PATH_RE = re.compile(
    r"(?:(?<=[\s\"'=:(])|(?<=^))/Users/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.\-]+)+",
    re.MULTILINE,
)
_LINUX_PATH_RE = re.compile(
    r"(?:(?<=[\s\"'=:(])|(?<=^))/home/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.\-]+)+",
    re.MULTILINE,
)
# Windows paths (for Tauri desktop users) — supports line-start
_WINDOWS_PATH_RE = re.compile(
    r"(?i)(?:(?<=[\s\"'=:(])|(?<=^))[A-Z]:\\(?:Users|Documents and Settings)\\[^\s\"']+",
    re.MULTILINE,
)
_PATH_RES = (_MACOS_PATH_RE, _LINUX_PATH_RE, _WINDOWS_PATH_RE)


class _SecretRule(NamedTuple):
    """One detector: the capture group holding the secret decides what gets replaced.

    ``name_group`` (0 = none) points at the key / flag capture group; the runtime
    redactor's keyword guard then decides whether that key really names a
    credential, so prose such as ``tokenizer=gpt2`` or ``os.getenv(...)`` lookups
    stay untouched.
    """

    pattern: re.Pattern[str]
    reason: str
    replacement: str
    value_group: int
    name_group: int = 0


# Specific detectors come before the generic key=value ones: when several rules match the
# same secret, the earliest rule supplies the label shown in the review.
_SECRET_RULES: tuple[_SecretRule, ...] = (
    _SecretRule(_PREFIX_RE, _TOKEN_PREFIX_REASON, "<REDACTED_TOKEN>", 1),
    _SecretRule(_AUTH_HEADER_RE, _AUTH_REASON, "<REDACTED_TOKEN>", 3),
    _SecretRule(_SECRET_HEADER_RE, _AUTH_REASON, "<REDACTED_TOKEN>", 2),
    _SecretRule(_URL_QUERY_RE, _URL_REASON, "<REDACTED_PARAM>", 2),
    _SecretRule(_URL_USERINFO_RE, _URL_CREDENTIAL_REASON, "***", 3),
    _SecretRule(_URL_BARE_TOKEN_RE, _URL_CREDENTIAL_REASON, "<REDACTED_TOKEN>", 2),
    _SecretRule(_DB_CONNSTR_RE, _DB_REASON, "***", 2),
    _SecretRule(_TELEGRAM_BOT_RE, _TELEGRAM_REASON, "<REDACTED_BOT_TOKEN>", 2),
    _SecretRule(_JSON_FIELD_RE, _JSON_REASON, "<REDACTED_SECRET>", 2),
    _SecretRule(_CLI_FLAG_RE, _CLI_REASON, "<REDACTED_VALUE>", 2, 1),
    _SecretRule(_ENV_ASSIGN_RE, _ENV_REASON, "<REDACTED_VALUE>", 2, 1),
    _SecretRule(_ENV_ASSIGN_LOWER_RE, _ENV_REASON, "<REDACTED_VALUE>", 2, 1),
    _SecretRule(_YAML_ASSIGN_RE, _CONFIG_REASON, "<REDACTED_VALUE>", 3, 1),
    _SecretRule(_JWT_RE, _TOKEN_PREFIX_REASON, "<REDACTED_TOKEN>", 0),
)


class _ScanMatch(TypedDict):
    start: int
    end: int
    replacement: str
    reason: str


class Redaction(TypedDict):
    line_number: int
    original: str
    redacted: str
    reason: str


@dataclass
class SanitizationResult:
    is_safe: bool
    redactions: list[Redaction]
    sanitized_content: str


def _secret_span(m: re.Match[str], group: int) -> tuple[int, int]:
    """Span of the secret itself; the quotes around a quoted value stay in place."""
    start, end = m.span(group)
    if end - start >= 2 and m.string[start] in "\"'" and m.string[end - 1] == m.string[start]:
        return start + 1, end - 1
    return start, end


def _resolve_overlaps(matches: list[_ScanMatch]) -> list[_ScanMatch]:
    """Keep the longest of any overlapping matches; result is ordered by start, last first.

    Last-first order lets replacements be applied in place without shifting the
    offsets of the matches still to come.
    """
    kept: list[_ScanMatch] = []
    for candidate in sorted(matches, key=lambda x: x["start"] - x["end"]):
        if all(candidate["start"] >= k["end"] or candidate["end"] <= k["start"] for k in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda x: x["start"], reverse=True)


class ContentSanitizer:
    """Skill content sanitizer for export-time privacy protection."""

    def _scan_line(self, line: str) -> list[_ScanMatch]:
        """Scan a single line for all sensitive patterns. Returns match info list."""
        matches: list[_ScanMatch] = []

        for rule in _SECRET_RULES:
            for m in rule.pattern.finditer(line):
                if rule.name_group and _redact_value(m.group(rule.name_group), m.group(rule.value_group)) is None:
                    continue
                start, end = _secret_span(m, rule.value_group)
                if start < end:
                    matches.append({"start": start, "end": end, "replacement": rule.replacement, "reason": rule.reason})

        for pattern in _PATH_RES:
            for m in pattern.finditer(line):
                matches.append(
                    {"start": m.start(), "end": m.end(), "replacement": "<REDACTED_PATH>", "reason": _PATH_REASON}
                )

        return matches

    def _sanitize_text(
        self, content: str, filename: str, ignored_indices: list[int] | None = None
    ) -> SanitizationResult:
        """Line-by-line scanning with structured Diff output."""
        redactions: list[Redaction] = []
        sanitized_lines = []
        ignored_indices = ignored_indices or []

        # Pre-compute PEM block interior lines (body lines that need redaction)
        pem_body_lines: set[int] = set()
        for m in _PRIVATE_KEY_RE.finditer(content):
            block_start = content[: m.start()].count("\n")
            block_end = content[: m.end()].count("\n")
            for ln in range(block_start + 1, block_end):
                pem_body_lines.add(ln)

        lines = content.splitlines()
        redaction_index = 0

        for i, line in enumerate(lines):
            original_line = line
            modified_line = line

            # PEM body lines: redact content between BEGIN/END markers
            if i in pem_body_lines:
                current_index = redaction_index
                redaction_index += 1
                if current_index not in ignored_indices:
                    modified_line = "...redacted..."
                    redactions.append(
                        Redaction(
                            line_number=i + 1,
                            original=original_line,
                            redacted=modified_line,
                            reason=_PEM_REASON,
                        )
                    )
                sanitized_lines.append(modified_line)
                continue

            line_matches = self._scan_line(original_line)

            if line_matches:
                current_index = redaction_index
                redaction_index += 1

                if current_index not in ignored_indices:
                    reasons: list[str] = []
                    for match_info in _resolve_overlaps(line_matches):
                        modified_line = (
                            modified_line[: match_info["start"]]
                            + match_info["replacement"]
                            + modified_line[match_info["end"] :]
                        )
                        if match_info["reason"] not in reasons:
                            reasons.append(match_info["reason"])

                    redactions.append(
                        Redaction(
                            line_number=i + 1,
                            original=original_line,
                            redacted=modified_line,
                            reason=" / ".join(reasons),
                        )
                    )

            sanitized_lines.append(modified_line)

        sanitized_content = "\n".join(sanitized_lines)
        if content.endswith("\n"):
            # splitlines() drops the final line break; a redacted file keeps the one it had.
            sanitized_content += "\n"
        return SanitizationResult(
            is_safe=len(redactions) == 0,
            redactions=redactions,
            sanitized_content=sanitized_content,
        )

    def sanitize(
        self,
        content: str | bytes,
        filename: str,
        ignored_indices: list[int] | None = None,
    ) -> SanitizationResult:
        """Scan and sanitize file content for export."""
        if isinstance(content, bytes):
            try:
                text_content = content.decode("utf-8")
            except UnicodeDecodeError:
                # Binary content cannot be treated as text — return an empty string
                # so the result keeps its ``str`` contract.
                return SanitizationResult(is_safe=True, redactions=[], sanitized_content="")
        else:
            text_content = content

        return self._sanitize_text(text_content, filename, ignored_indices)


content_sanitizer = ContentSanitizer()
