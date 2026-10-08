"""
[POS] src/myrm_agent_harness/core/security/assignment_sweep/quoted_sweep_engine.py
[INPUT] re, typing, types, database_url_auditor
[OUTPUT] QuotedKeySecretAssignmentSweepEngine
Secret assignment sweep engine tolerating quoted keys, separator-prefixed words, and alphanumeric noise shielding.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re

from .database_url_auditor import DatabaseUrlAuditor
from .types import (
    AssignmentFormat,
    AssignmentKeyFamily,
    AssignmentSweepFinding,
    AssignmentSweepReport,
    AssignmentSweepVerdict,
)

logger = logging.getLogger(__name__)

# Common dummy or placeholder values that do not represent active secrets
_PLACEHOLDER_RE = re.compile(
    r"^(?:your[_-].*|xxx+|placeholder|example|changeme|TODO|CHANGE_ME|INSERT_HERE|"
    r"<[^>]+>|\$\{[^}]+\}|%\([^)]+\)s|None|null|undefined|test|demo|fake|dummy|sample|"
    r"bearer\s+token|secret_key|api_key|password)$",
    re.IGNORECASE,
)

# Alphanumeric run words that resemble secret keys but are innocent code symbols
_BENIGN_SYMBOL_PREFIXES: frozenset[str] = frozenset(
    {
        "tokenizer",
        "tokenize",
        "token_count",
        "token_type",
        "token_endpoint",
        "tokens_used",
        "secretive",
        "credentials_file",
        "credential_path",
        "credential_cache",
        "password_reset",
        "password_reset_url",
        "password_hash",
        "secret_path",
    }
)

# Robust pattern matching quoted/unquoted key assignments:
# Covers: "api_key": "xxx", 'client_secret': 'xxx', `MY_API_KEY`: `xxx`,
#         MY_API_KEY = "xxx", os.environ["API_KEY"] = "xxx", config['secret'] = 'xxx'
_ASSIGNMENT_PATTERN = re.compile(
    r"""
    (?P<prefix>os\.environ\[|config\[|params\[)?          # Optional dictionary/env bracket
    (?P<open_q>["'`])?                                    # Optional open quote on key
    (?P<key>(?:[a-zA-Z0-9_]*[_-])?                        # Optional prefix before sensitive token
            (?:api[_-]?key|secret[_-]?key|access[_-]?key|client[_-]?secret|app[_-]?secret|
               auth[_-]?token|access[_-]?token|signing[_-]?key|private[_-]?key|
               password|passwd|pwd|passphrase|secret|token|credential|credentials|密码|口令))
    (?P=open_q)?                                          # Matching quote on key if present
    (?(prefix)\])                                         # Close bracket if dict/env bracket was present
    \s*(?P<delim>[:=：])\s*                               # Delimiter : or =
    (?P<val_open_q>["'`])?                                # Optional open quote on value
    (?P<value>[^\s"';,\n\r}\]]+)                          # Extracted assigned value
    (?P=val_open_q)?                                      # Matching close quote on value if present
    """,
    re.IGNORECASE | re.VERBOSE,
)


class QuotedKeySecretAssignmentSweepEngine:
    """Engine scanning source code, YAML, JSON, and .env files for sensitive assignments."""

    def __init__(self, dsn_auditor: DatabaseUrlAuditor | None = None) -> None:
        self._dsn_auditor = dsn_auditor or DatabaseUrlAuditor()

    @staticmethod
    def _classify_key_family(key_name: str) -> AssignmentKeyFamily:
        k = key_name.lower()
        if any(w in k for w in ("password", "passwd", "pwd", "passphrase", "密码", "口令")):
            return AssignmentKeyFamily.PASSWORD
        if any(w in k for w in ("api_key", "apikey", "access_key", "signing_key", "private_key")):
            return AssignmentKeyFamily.API_KEY
        if any(w in k for w in ("client_secret", "app_secret", "secret_key", "secret")):
            return AssignmentKeyFamily.SECRET
        if any(w in k for w in ("access_token", "auth_token", "token")):
            return AssignmentKeyFamily.TOKEN
        return AssignmentKeyFamily.CREDENTIAL

    @staticmethod
    def _classify_format(line: str, key: str, delim: str) -> AssignmentFormat:
        if "[" in line and "]" in line:
            return AssignmentFormat.ENV_BRACKET
        if line.strip().startswith(("{", '"', "'")) and delim in {":", "："}:
            return AssignmentFormat.QUOTED_JSON
        if delim == "=":
            return AssignmentFormat.EQUALS_ASSIGNMENT
        return AssignmentFormat.COLON_ASSIGNMENT

    @staticmethod
    def _is_benign_token(key: str, value: str) -> bool:
        """Filter out benign alphanumeric continuous symbols and standard placeholders."""
        k_clean = key.strip().lower()
        v_clean = value.strip()

        # Check known benign code symbols (tokenizer, secretive, credentials_file, etc.)
        for benign in _BENIGN_SYMBOL_PREFIXES:
            if k_clean == benign or k_clean.startswith(f"{benign}_"):
                return True

        # Check placeholder expressions
        if _PLACEHOLDER_RE.match(v_clean):
            return True

        # Ignore trivially short values (e.g. "0", "true", "none")
        return len(v_clean) < 4

    @staticmethod
    def _mask_value(value: str) -> str:
        """Create masked preview to prevent log poisoning while retaining diagnostics."""
        clean = value.strip("\"'")
        if len(clean) <= 6:
            return "***"
        return f"{clean[:3]}...{clean[-3:]}"

    def scan_content(self, content: str) -> AssignmentSweepReport:
        """Scan multiline string or config content for quoted-key secrets and database URLs."""
        findings: list[AssignmentSweepFinding] = []
        lines = content.splitlines()

        # 1. Quoted-key and env-bracket assignment scanning
        for line in lines:
            trimmed = line.strip()
            if not trimmed or trimmed.startswith(("#", "//", "/*", "*")):
                continue

            for match in _ASSIGNMENT_PATTERN.finditer(trimmed):
                key = match.group("key")
                val = match.group("value")
                delim = match.group("delim")

                if self._is_benign_token(key, val):
                    continue

                family = self._classify_key_family(key)
                format_kind = self._classify_format(trimmed, key, delim)

                finding = AssignmentSweepFinding(
                    key_name=key,
                    key_family=family,
                    raw_matched_line=trimmed[:200],
                    value_preview=self._mask_value(val),
                    format_kind=format_kind,
                    is_exempt=False,
                )
                findings.append(finding)

        # 2. Database DSN auditing with loopback exemption
        dsn_results = self._dsn_auditor.extract_and_audit_all(content)
        for dsn in dsn_results:
            findings.append(
                AssignmentSweepFinding(
                    key_name=f"{dsn.scheme}://{dsn.user}@{dsn.host}",
                    key_family=AssignmentKeyFamily.DATABASE_URL,
                    raw_matched_line=dsn.raw_url[:150],
                    value_preview=self._mask_value(dsn.raw_url),
                    format_kind=AssignmentFormat.DATABASE_DSN,
                    is_exempt=dsn.is_exempt,
                    exemption_reason=dsn.audit_reason if dsn.is_exempt else None,
                )
            )

        active_leaks = [f for f in findings if not f.is_exempt]
        exempted = [f for f in findings if f.is_exempt]

        if active_leaks:
            verdict = AssignmentSweepVerdict.SUSPECTED_LEAK
        elif exempted:
            verdict = AssignmentSweepVerdict.EXEMPTED_LOCAL_DEV
        else:
            verdict = AssignmentSweepVerdict.CLEAN

        return AssignmentSweepReport(
            total_lines_scanned=len(lines),
            findings=findings,
            verdict=verdict,
            active_leaks_count=len(active_leaks),
            exempted_count=len(exempted),
        )
