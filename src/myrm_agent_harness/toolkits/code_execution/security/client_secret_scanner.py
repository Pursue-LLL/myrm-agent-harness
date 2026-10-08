"""Client-side code secret leak detection scanner.

[POS]
Detects hardcoded secrets, API tokens, and database connection strings in
browser-facing code (React, Next.js, Vue, HTML, Svelte, JS/TS).
Prevents catastrophic public exposure via browser developer tools (F12)
and public build artifacts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SecretFinding:
    """Represents a hardcoded secret detected in client-side code."""

    secret_type: str
    pattern_name: str
    line_number: int
    matched_snippet: str
    suggested_env_var: str
    file_path: str


# Extensions typically delivered or executed in the browser
CLIENT_CODE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".tsx",
        ".jsx",
        ".vue",
        ".svelte",
        ".html",
        ".htm",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
    }
)

# Directories specifically dedicated to client/browser code
CLIENT_PATH_HINTS: tuple[str, ...] = (
    "components/",
    "pages/",
    "views/",
    "client/",
    "frontend/",
    "public/",
    "app/(",
    "src/",
)

# High-precision patterns for sensitive tokens and credentials
_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "OpenAI API Key",
        "OPENAI_API_KEY",
        re.compile(r"""(?:sk-[a-zA-Z0-9_-]{20,}|sk-proj-[a-zA-Z0-9_-]{40,})"""),
    ),
    (
        "GitHub Personal Access Token",
        "GITHUB_TOKEN",
        re.compile(r"""(?:ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{50,})"""),
    ),
    (
        "Stripe Secret Key",
        "STRIPE_SECRET_KEY",
        re.compile(r"""(?:sk_live_[a-zA-Z0-9]{24,}|rk_live_[a-zA-Z0-9]{24,}|sk_test_[a-zA-Z0-9]{24,})"""),
    ),
    (
        "Database Connection URL",
        "DATABASE_URL",
        re.compile(
            r"""(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[a-zA-Z0-9_]+:[^@\s]+@[a-zA-Z0-9_.-]+(?::\d+)?/[^\s"'`]+"""
        ),
    ),
    (
        "Private Key PEM Block",
        "PRIVATE_KEY",
        re.compile(r"""-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"""),
    ),
    (
        "Generic Sensitive Variable Assignment",
        "API_SECRET_KEY",
        re.compile(
            r"""(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*["']([a-zA-Z0-9_-]{24,})["']"""
        ),
    ),
)


class ClientSideSecretScanner:
    """Scanner for detecting hardcoded secrets in browser-facing code."""

    @classmethod
    def is_client_code_file(cls, file_path: str) -> bool:
        """Determine whether the specified file path targets client-side execution."""
        path_obj = Path(file_path)
        ext = path_obj.suffix.lower()
        if ext not in CLIENT_CODE_EXTENSIONS:
            return False

        # Exclude server-only directories or files
        norm_path = file_path.replace("\\", "/").lower()
        return not ("/api/" in norm_path or norm_path.endswith((".server.ts", ".server.js")))

    @classmethod
    def scan_code(cls, code: str, file_path: str) -> list[SecretFinding]:
        """Scan code content and return all detected secret findings."""
        if not cls.is_client_code_file(file_path):
            return []

        findings: list[SecretFinding] = []
        lines = code.splitlines()

        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Skip empty lines or pure comment lines
            if not stripped or stripped.startswith(("//", "/*", "*", "#")):
                continue

            for pattern_name, env_var, pattern in _PATTERNS:
                match = pattern.search(line)
                if match:
                    raw_matched = match.group(0)
                    # Mask snippet for safety
                    if len(raw_matched) > 8:
                        masked = raw_matched[:4] + "****" + raw_matched[-4:]
                    else:
                        masked = "****"

                    findings.append(
                        SecretFinding(
                            secret_type=pattern_name,
                            pattern_name=pattern_name,
                            line_number=line_idx,
                            matched_snippet=masked,
                            suggested_env_var=env_var,
                            file_path=file_path,
                        )
                    )

        return findings
