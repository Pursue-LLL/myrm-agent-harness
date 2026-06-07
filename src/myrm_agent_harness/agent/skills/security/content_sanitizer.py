"""Content Sanitizer - 技能导出内容脱敏

Scans and redacts sensitive information (API keys, tokens, absolute paths,
credentials, PEM keys, DB connection strings) from skill files before export.
Two-stage design: scan → return structured Diff → user confirms → apply.

Reuses proven patterns from core/security/redact.py (runtime redactor) to
ensure export-time detection parity with runtime masking.

[INPUT]
- core.security.redact (POS: Compiled regex patterns for token prefix and context-based detection)

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
from typing import TypedDict

from myrm_agent_harness.core.security.redact import (
    _AUTH_HEADER_RE,
    _CLI_FLAG_RE,
    _DB_CONNSTR_RE,
    _ENV_ASSIGN_RE,
    _JSON_FIELD_RE,
    _PREFIX_RE,
    _PRIVATE_KEY_RE,
    _TELEGRAM_BOT_RE,
    _URL_QUERY_RE,
)

logger = logging.getLogger(__name__)

# ── Pattern categories for structured redaction ──────────────────────────────
# Each entry: (compiled_pattern, reason_label, replacement_template)
# For patterns with capture groups, group(0) is the full match unless noted.

_TOKEN_PREFIX_REASON = "API Key / Token"
_ENV_REASON = "Environment Variable"
_JSON_REASON = "JSON Secret Field"
_DB_REASON = "Database Credential"
_URL_REASON = "URL Secret Parameter"
_CLI_REASON = "CLI Secret Flag"
_TELEGRAM_REASON = "Telegram Bot Token"
_AUTH_REASON = "Authorization Header"
_PEM_REASON = "Private Key"
_PATH_REASON = "Absolute Path"

# Absolute paths (macOS/Linux) — supports line-start via (?:^|...) with MULTILINE
_MACOS_PATH_RE = re.compile(r"(?:(?<=[\s\"'=:(])|(?<=^))/Users/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.\-]+)+", re.MULTILINE)
_LINUX_PATH_RE = re.compile(r"(?:(?<=[\s\"'=:(])|(?<=^))/home/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.\-]+)+", re.MULTILINE)
# Windows paths (for Tauri desktop users) — supports line-start
_WINDOWS_PATH_RE = re.compile(
    r"(?i)(?:(?<=[\s\"'=:(])|(?<=^))[A-Z]:\\(?:Users|Documents and Settings)\\[^\s\"']+", re.MULTILINE
)


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


class ContentSanitizer:
    """Skill content sanitizer for export-time privacy protection."""

    def _scan_line(self, line: str) -> list[dict]:
        """Scan a single line for all sensitive patterns. Returns match info list."""
        matches: list[dict] = []

        # 1. Token prefix patterns (28 formats: ghp_, AKIA, sk_live_, etc.)
        for m in _PREFIX_RE.finditer(line):
            matches.append(
                {
                    "start": m.start(1),
                    "end": m.end(1),
                    "replacement": "<REDACTED_TOKEN>",
                    "reason": _TOKEN_PREFIX_REASON,
                }
            )

        # 2. Environment variable assignments (API_KEY=xxx, SECRET=xxx)
        for m in _ENV_ASSIGN_RE.finditer(line):
            matches.append(
                {
                    "start": m.start(3),
                    "end": m.end(3),
                    "replacement": "<REDACTED_VALUE>",
                    "reason": _ENV_REASON,
                }
            )

        # 3. JSON secret fields ("token": "xxx")
        for m in _JSON_FIELD_RE.finditer(line):
            matches.append(
                {
                    "start": m.start(2),
                    "end": m.end(2),
                    "replacement": "<REDACTED_SECRET>",
                    "reason": _JSON_REASON,
                }
            )

        # 4. Database connection strings (postgres://user:PASS@host)
        for m in _DB_CONNSTR_RE.finditer(line):
            matches.append(
                {
                    "start": m.start(2),
                    "end": m.end(2),
                    "replacement": "***",
                    "reason": _DB_REASON,
                }
            )

        # 5. URL query parameters (?api_key=xxx)
        for m in _URL_QUERY_RE.finditer(line):
            matches.append(
                {
                    "start": m.start(1),
                    "end": m.end(1),
                    "replacement": "<REDACTED_PARAM>",
                    "reason": _URL_REASON,
                }
            )

        # 6. CLI flags (--api-key xxx, --token xxx)
        for m in _CLI_FLAG_RE.finditer(line):
            matches.append(
                {
                    "start": m.start(2),
                    "end": m.end(2),
                    "replacement": "<REDACTED_VALUE>",
                    "reason": _CLI_REASON,
                }
            )

        # 7. Telegram bot tokens (bot123456:ABC-xxx)
        for m in _TELEGRAM_BOT_RE.finditer(line):
            matches.append(
                {
                    "start": m.start(1),
                    "end": m.end(1),
                    "replacement": "<REDACTED_BOT_TOKEN>",
                    "reason": _TELEGRAM_REASON,
                }
            )

        # 8. Authorization headers (Bearer token)
        for m in _AUTH_HEADER_RE.finditer(line):
            matches.append(
                {
                    "start": m.start(2),
                    "end": m.end(2),
                    "replacement": "<REDACTED_TOKEN>",
                    "reason": _AUTH_REASON,
                }
            )

        # 9. Absolute paths (macOS, Linux, Windows)
        for pattern in (_MACOS_PATH_RE, _LINUX_PATH_RE, _WINDOWS_PATH_RE):
            for m in pattern.finditer(line):
                matches.append(
                    {
                        "start": m.start(),
                        "end": m.end(),
                        "replacement": "<REDACTED_PATH>",
                        "reason": _PATH_REASON,
                    }
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
                    # Sort by start position descending to avoid index shift
                    line_matches.sort(key=lambda x: x["start"], reverse=True)

                    # Deduplicate overlapping matches (keep the longest)
                    filtered: list[dict] = []
                    for match_info in line_matches:
                        overlaps = False
                        for existing in filtered:
                            if match_info["start"] < existing["end"] and match_info["end"] > existing["start"]:
                                overlaps = True
                                break
                        if not overlaps:
                            filtered.append(match_info)

                    reasons = []
                    for match_info in filtered:
                        start = match_info["start"]
                        end = match_info["end"]
                        modified_line = modified_line[:start] + match_info["replacement"] + modified_line[end:]
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

        return SanitizationResult(
            is_safe=len(redactions) == 0,
            redactions=redactions,
            sanitized_content="\n".join(sanitized_lines),
        )

    def sanitize(
        self, content: str | bytes, filename: str, ignored_indices: list[int] | None = None
    ) -> SanitizationResult:
        """Scan and sanitize file content for export."""
        if isinstance(content, bytes):
            try:
                text_content = content.decode("utf-8")
            except UnicodeDecodeError:
                return SanitizationResult(is_safe=True, redactions=[], sanitized_content=content)
        else:
            text_content = content

        return self._sanitize_text(text_content, filename, ignored_indices)


content_sanitizer = ContentSanitizer()
