"""Shell bleed detection — scan scripts for sensitive environment variable references.

Detects references to environment variables that may leak secrets (API keys,
tokens, passwords) within script files executed by the agent.

Produces **warnings only** — does not block execution. Integration points
can call ``scan_file_for_env_leaks()`` before executing user-provided or
LLM-generated script files and log the warnings.

Inspired by openfang's shell_bleed.rs.

[INPUT]
- (none)

[OUTPUT]
- ShellBleedWarning: A detected environment variable reference that may leak s...
- scan_content_for_env_leaks: Scan text content for references to suspicious environmen...
- scan_file_for_env_leaks: Scan a script file for suspicious environment variable re...

[POS]
Shell bleed detection — scan scripts for sensitive environment variable references.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SAFE_ENV_REFS: frozenset[str] = frozenset(
    {
        "HOME",
        "USER",
        "PATH",
        "SHELL",
        "PWD",
        "OLDPWD",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TMPDIR",
        "TMP",
        "TEMP",
        "HOSTNAME",
        "LOGNAME",
        "SHLVL",
        "LINES",
        "COLUMNS",
        "XDG_RUNTIME_DIR",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "EDITOR",
        "VISUAL",
        "PAGER",
        "COLORTERM",
        "OSTYPE",
        "HOSTTYPE",
        "MACHTYPE",
        "_",
    }
)

SCRIPT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ksh",
        ".csh",
        ".py",
        ".rb",
        ".pl",
        ".js",
        ".ts",
    }
)

_SUSPICIOUS_KEYWORDS: tuple[str, ...] = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "CREDENTIAL",
    "APIKEY",
    "API_KEY",
    "PASSPHRASE",
    "AUTH",
)

_ENV_VAR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\$([A-Z_][A-Z0-9_]*)"), "shell $VAR"),
    (re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}"), "shell ${VAR}"),
    (re.compile(r"os\.environ\[[\"\']([A-Z_][A-Z0-9_]*)[\"\']\]"), "Python os.environ"),
    (re.compile(r"os\.getenv\([\"\']([A-Z_][A-Z0-9_]*)[\"\']"), "Python os.getenv"),
    (re.compile(r"process\.env\.([A-Z_][A-Z0-9_]*)"), "Node process.env"),
    (re.compile(r"ENV\[[\"\']([A-Z_][A-Z0-9_]*)[\"\']\]"), "Ruby ENV"),
)

MAX_SCAN_SIZE: int = 512 * 1024


@dataclass(frozen=True, slots=True)
class ShellBleedWarning:
    """A detected environment variable reference that may leak secrets."""

    var_name: str
    line_number: int
    access_pattern: str
    reason: str


def _is_suspicious_var(name: str) -> bool:
    """Check if a variable name looks like it holds sensitive data."""
    upper = name.upper()
    return any(kw in upper for kw in _SUSPICIOUS_KEYWORDS)


def scan_content_for_env_leaks(
    content: str,
    *,
    source: str = "<inline>",
) -> list[ShellBleedWarning]:
    """Scan text content for references to suspicious environment variables.

    Args:
        content: Script content to scan.
        source: Label for log messages (e.g. file path).

    Returns:
        List of warnings for suspicious env var references found.
    """
    if not content:
        return []

    warnings: list[ShellBleedWarning] = []
    seen: set[tuple[str, int]] = set()

    for line_idx, line in enumerate(content.splitlines(), start=1):
        for pattern, access_type in _ENV_VAR_PATTERNS:
            for match in pattern.finditer(line):
                var_name = match.group(1)
                if var_name in SAFE_ENV_REFS:
                    continue
                if not _is_suspicious_var(var_name):
                    continue
                dedup_key = (var_name, line_idx)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                warnings.append(
                    ShellBleedWarning(
                        var_name=var_name,
                        line_number=line_idx,
                        access_pattern=access_type,
                        reason=f"Suspicious env var reference: {var_name}",
                    )
                )

    if warnings:
        logger.warning(
            "Shell bleed: %d suspicious env var reference(s) in %s: %s",
            len(warnings),
            source,
            ", ".join(sorted({w.var_name for w in warnings})),
        )

    return warnings


def scan_file_for_env_leaks(file_path: str | Path) -> list[ShellBleedWarning]:
    """Scan a script file for suspicious environment variable references.

    Skips files that are too large (> 512 KB) or have non-script extensions.

    Args:
        file_path: Path to the script file.

    Returns:
        List of warnings. Empty if the file is not a script or too large.
    """
    path = Path(file_path)

    if path.suffix.lower() not in SCRIPT_EXTENSIONS:
        return []

    try:
        size = path.stat().st_size
        if size > MAX_SCAN_SIZE:
            logger.debug("Shell bleed: skipping %s (%.1f KB > %d KB limit)", path, size / 1024, MAX_SCAN_SIZE // 1024)
            return []
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("Shell bleed: cannot read %s: %s", path, e)
        return []

    return scan_content_for_env_leaks(content, source=str(path))
