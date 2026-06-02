"""Security preflight checks for bash command execution.

[INPUT]
utils.url_utils::check_url_exfiltration, sanitize_url_for_error (POS: URL security validation)
utils.errors::ToolError (POS: Agent tool error with format_for_llm protocol)

[OUTPUT]
check_command_url_exfiltration: Block commands with URL data exfiltration.
check_sensitive_paths: Block commands accessing sensitive directories.
check_interactive_command: Detect commands requiring interactive stdin.

[POS]
Security preflight for bash commands. Validates URLs against data exfiltration,
blocks access to sensitive paths (.ssh, .aws, etc.), and detects interactive
commands that would hang in a non-TTY environment.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL Exfiltration Detection
# ---------------------------------------------------------------------------

_URL_EXTRACTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r'curl\s+[^|;&]*?(https?://[^\s\'"]+)',
        r'wget\s+[^|;&]*?(https?://[^\s\'"]+)',
        r'fetch\s+[^|;&]*?(https?://[^\s\'"]+)',
        r'http-get\s+[^|;&]*?(https?://[^\s\'"]+)',
        r'(https?://[^\s\'"]+)',
    ]
)


def check_command_url_exfiltration(command: str) -> None:
    """Block commands containing URLs with sensitive data (API keys, credentials).

    Raises:
        ToolError: If URL contains data exfiltration patterns.
    """
    from myrm_agent_harness.utils.errors import ToolError
    from myrm_agent_harness.utils.url_utils import (
        check_url_exfiltration,
        sanitize_url_for_error,
    )

    detected_urls: list[str] = []
    for pattern in _URL_EXTRACTION_PATTERNS:
        detected_urls.extend(pattern.findall(command))

    for url in set(detected_urls):
        warnings = check_url_exfiltration(url, allow_private_networks=True)
        if warnings:
            safe_url = sanitize_url_for_error(url)
            logger.warning(f" Data exfiltration detected in bash command: {command[:100]}")
            for warning in warnings:
                logger.warning(f" - {warning} in URL: {safe_url}")
            raise ToolError(
                f"Command blocked (data exfiltration): {'; '.join(warnings)} — URL: {safe_url}",
                user_hint="The command contains a URL with sensitive data (API keys, file paths, or credentials). Remove sensitive data from the URL.",
            )


# ---------------------------------------------------------------------------
# Sensitive Path Preflight
# ---------------------------------------------------------------------------

_SENSITIVE_PATH_RE = re.compile(
    r'(?:^|[\s"\'=/])(?:\.ssh|\.aws|\.npmrc|\.gnupg|\.docker|\.kube|\.bash_history|\.zsh_history)(?:/|[\s"\']|$)',
    re.IGNORECASE,
)


def check_sensitive_paths(command: str) -> None:
    """Block commands that access sensitive directories (.ssh, .aws, etc.).

    Raises:
        ToolError: If sensitive path access is detected.
    """
    from myrm_agent_harness.utils.errors import ToolError

    if match := _SENSITIVE_PATH_RE.search(command):
        sensitive_path = match.group(0).strip(" \"'=/")
        logger.warning(f" Sensitive path access detected: {command[:100]}")
        raise ToolError(
            f"Command blocked (security): Access to sensitive path '{sensitive_path}' is strictly prohibited.",
            user_hint=f"The command attempts to access a protected path ({sensitive_path}). This is blocked by the security sandbox.",
        )


# ---------------------------------------------------------------------------
# Interactive Command Preflight
# ---------------------------------------------------------------------------

_SCAFFOLD_MARKERS: tuple[str, ...] = (
    "create-next-app",
    "npm create ",
    "npm init",
    "pnpm create ",
    "pnpm init",
    "yarn create ",
    "yarn init",
    "bun create ",
    "bunx create-",
    "npx create-",
)

_SCAFFOLD_NON_INTERACTIVE_RE = re.compile(
    r"(?:--yes\b|(?:^|\s)-y(?:\s|$)|--skip-install\b|--defaults\b|--non-interactive\b|--ci\b)",
    re.IGNORECASE,
)

_GIT_COMMIT_RE = re.compile(r"\bgit\s+commit\b")
_GIT_COMMIT_MSG_RE = re.compile(r"(?:\s-[a-zA-Z]*m[\s\"']|\s--message[\s=]|\s-F\s|\s--file[\s=])")
_GIT_INTERACTIVE_RE = re.compile(r"\bgit\s+(?:rebase\s+(?:-i|--interactive)|add\s+(?:-i|-p|--interactive|--patch))\b")
_POETRY_INIT_RE = re.compile(r"\bpoetry\s+init\b")


def check_interactive_command(command: str) -> str | None:
    """Detect commands that require interactive stdin and would hang.

    Returns an error message if interactive, None if safe.
    """
    lowered = command.lower()

    if any(marker in lowered for marker in _SCAFFOLD_MARKERS) and not _SCAFFOLD_NON_INTERACTIVE_RE.search(lowered):
        return (
            "This command requires interactive input (template/option selection). "
            "The bash tool cannot answer prompts. "
            "Use non-interactive flags: --yes, -y, --defaults, or specify all options inline."
        )

    if _GIT_COMMIT_RE.search(lowered) and not _GIT_COMMIT_MSG_RE.search(command):
        return (
            'git commit without -m/--message opens an editor for interactive input. Use: git commit -m "your message"'
        )

    if _GIT_INTERACTIVE_RE.search(lowered):
        return (
            "This git command opens an interactive editor/UI. The bash tool cannot handle interactive git operations."
        )

    if _POETRY_INIT_RE.search(lowered) and "--no-interaction" not in lowered:
        return "poetry init requires interactive input. Use: poetry init --no-interaction"

    return None
