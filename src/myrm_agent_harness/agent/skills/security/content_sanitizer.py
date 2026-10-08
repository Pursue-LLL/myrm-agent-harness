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
- SecretKind: Literal — closed set of finding kinds; callers render them in their own language
- Redaction: TypedDict — single redaction finding (``kinds`` instead of display text)
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
from typing import Literal, NamedTuple, TypedDict

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

SecretKind = Literal[
    "api_token",
    "environment_variable",
    "config_secret",
    "json_secret_field",
    "database_credential",
    "url_secret_parameter",
    "url_credential",
    "cli_secret_flag",
    "telegram_bot_token",
    "authorization_header",
    "private_key",
    "absolute_path",
]

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

# A value that points at a secret instead of containing one: shell / CI variable, template
# placeholder, angle-bracket stand-in, or an ALL_CAPS variable name.
_PLACEHOLDER_RE = re.compile(r"\$[{(A-Za-z_]|\{\{|%[^%\s]+%$|<[^<>\s]*>$|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")

# A key whose keyword describes a setting about a secret (limits, kinds, pointers), not the secret.
_NON_SECRET_KEY_RE = re.compile(
    r"(?:tokens|[_.\-](?:type|name|method|mode|scheme|url|uri|endpoint|file|path|env|var|header|field"
    r"|limit|count|budget|ttl|expiry|expires?))$",
    re.IGNORECASE,
)


class _SecretRule(NamedTuple):
    """One detector: the capture group holding the secret decides what gets replaced.

    ``name_group`` (0 = none) points at the key / flag capture group; the runtime
    redactor's keyword guard then decides whether that key really names a
    credential, so prose such as ``tokenizer=gpt2`` or ``os.getenv(...)`` lookups
    stay untouched. Every rule's groups must exist in its pattern.
    """

    pattern: re.Pattern[str]
    kind: SecretKind
    replacement: str
    value_group: int
    name_group: int = 0


# Specific detectors come before the generic key=value ones: when several rules match the
# same secret, the earliest rule supplies the kind shown in the review.
_SECRET_RULES: tuple[_SecretRule, ...] = (
    _SecretRule(_PREFIX_RE, "api_token", "<REDACTED_TOKEN>", 1),
    _SecretRule(_AUTH_HEADER_RE, "authorization_header", "<REDACTED_TOKEN>", 3),
    _SecretRule(_SECRET_HEADER_RE, "authorization_header", "<REDACTED_TOKEN>", 2),
    _SecretRule(_URL_QUERY_RE, "url_secret_parameter", "<REDACTED_PARAM>", 2),
    _SecretRule(_URL_USERINFO_RE, "url_credential", "***", 3),
    _SecretRule(_URL_BARE_TOKEN_RE, "url_credential", "<REDACTED_TOKEN>", 2),
    _SecretRule(_DB_CONNSTR_RE, "database_credential", "***", 2),
    _SecretRule(_TELEGRAM_BOT_RE, "telegram_bot_token", "<REDACTED_BOT_TOKEN>", 2),
    _SecretRule(_JSON_FIELD_RE, "json_secret_field", "<REDACTED_SECRET>", 2),
    _SecretRule(_CLI_FLAG_RE, "cli_secret_flag", "<REDACTED_VALUE>", 2, 1),
    _SecretRule(_ENV_ASSIGN_RE, "environment_variable", "<REDACTED_VALUE>", 2, 1),
    _SecretRule(_ENV_ASSIGN_LOWER_RE, "environment_variable", "<REDACTED_VALUE>", 2, 1),
    _SecretRule(_YAML_ASSIGN_RE, "config_secret", "<REDACTED_VALUE>", 3, 1),
    _SecretRule(_JWT_RE, "api_token", "<REDACTED_TOKEN>", 0),
)


class _ScanMatch(TypedDict):
    start: int
    end: int
    replacement: str
    kind: SecretKind


class Redaction(TypedDict):
    """One finding on one line; ``kinds`` are stable codes the caller renders in its own language."""

    line_number: int
    original: str
    redacted: str
    kinds: list[SecretKind]


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


def _merge_overlaps(matches: list[_ScanMatch]) -> list[_ScanMatch]:
    """Union overlapping matches so no part of a secret is left behind; last match first.

    The longest member of each union supplies the replacement and the kind. Last-first
    order lets replacements be applied in place without shifting the offsets still to come.
    """
    clusters: list[list[_ScanMatch]] = []
    cluster_end = 0
    for match in sorted(matches, key=lambda x: x["start"]):
        if clusters and match["start"] < cluster_end:
            clusters[-1].append(match)
            cluster_end = max(cluster_end, match["end"])
        else:
            clusters.append([match])
            cluster_end = match["end"]

    merged: list[_ScanMatch] = []
    for cluster in reversed(clusters):
        lead = max(cluster, key=lambda x: x["end"] - x["start"])
        merged.append(
            {
                "start": cluster[0]["start"],
                "end": max(x["end"] for x in cluster),
                "replacement": lead["replacement"],
                "kind": lead["kind"],
            }
        )
    return merged


class ContentSanitizer:
    """Skill content sanitizer for export-time privacy protection."""

    def _scan_line(self, line: str) -> list[_ScanMatch]:
        """Scan a single line for all sensitive patterns. Returns match info list."""
        matches: list[_ScanMatch] = []

        for rule in _SECRET_RULES:
            for m in rule.pattern.finditer(line):
                start, end = _secret_span(m, rule.value_group)
                if start >= end or _PLACEHOLDER_RE.match(line, start, end):
                    continue
                if rule.name_group:
                    name = m.group(rule.name_group)
                    if (
                        _NON_SECRET_KEY_RE.search(name.strip(" \t="))
                        or _redact_value(name, m.group(rule.value_group)) is None
                    ):
                        continue
                matches.append({"start": start, "end": end, "replacement": rule.replacement, "kind": rule.kind})

        for pattern in _PATH_RES:
            for m in pattern.finditer(line):
                matches.append(
                    {"start": m.start(), "end": m.end(), "replacement": "<REDACTED_PATH>", "kind": "absolute_path"}
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
                            kinds=["private_key"],
                        )
                    )
                sanitized_lines.append(modified_line)
                continue

            line_matches = self._scan_line(original_line)

            if line_matches:
                current_index = redaction_index
                redaction_index += 1

                if current_index not in ignored_indices:
                    kinds: list[SecretKind] = []
                    for match_info in _merge_overlaps(line_matches):
                        modified_line = (
                            modified_line[: match_info["start"]]
                            + match_info["replacement"]
                            + modified_line[match_info["end"] :]
                        )
                        kinds.append(match_info["kind"])

                    redactions.append(
                        Redaction(
                            line_number=i + 1,
                            original=original_line,
                            redacted=modified_line,
                            # Replacements run last-first; report kinds in reading order.
                            kinds=list(dict.fromkeys(reversed(kinds))),
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
