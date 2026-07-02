"""Security preflight checks for bash command execution.

[INPUT]
utils.url_utils::check_url_exfiltration, sanitize_url_for_error (POS: URL security validation)
utils.errors::ToolError (POS: Agent tool error with format_for_llm protocol)

[OUTPUT]
check_command_url_exfiltration: Block commands with URL data exfiltration.
check_sensitive_paths: Block commands accessing sensitive directories.
check_interactive_command: Detect commands requiring interactive stdin.
check_install_packages: Verify install package names exist on public registries.

[POS]
Security preflight for bash commands. Validates URLs against data exfiltration,
blocks access to sensitive paths (.ssh, .aws, etc.), detects interactive
commands that would hang in a non-TTY environment, and verifies package names
in install commands against public registries (anti-slopsquatting).
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.error
import urllib.request

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


# ---------------------------------------------------------------------------
# Install Package Registry Verification (Anti-Slopsquatting)
# ---------------------------------------------------------------------------

_PIP_INSTALL_RE = re.compile(
    r"(?:pip3?|python3?\s+-m\s+pip|uv\s+pip)\s+install\s+(.+?)(?:\s*(?:&&|;|\|)\s*|$)",
    re.IGNORECASE,
)
_UV_ADD_RE = re.compile(
    r"uv\s+add\s+(.+?)(?:\s*(?:&&|;|\|)\s*|$)",
    re.IGNORECASE,
)
_NPM_INSTALL_RE = re.compile(
    r"(?:npm|pnpm)\s+(?:install|i|add)\s+(.+?)(?:\s*(?:&&|;|\|)\s*|$)",
    re.IGNORECASE,
)
_YARN_ADD_RE = re.compile(
    r"yarn\s+add\s+(.+?)(?:\s*(?:&&|;|\|)\s*|$)",
    re.IGNORECASE,
)
_BUN_ADD_RE = re.compile(
    r"bun\s+(?:add|install)\s+(.+?)(?:\s*(?:&&|;|\|)\s*|$)",
    re.IGNORECASE,
)

_PRIVATE_REGISTRY_RE = re.compile(
    r"--(?:index-url|extra-index-url|registry)\b",
    re.IGNORECASE,
)

_LOCAL_PACKAGE_PREFIXES = ("./", "../", "file://", "git+", "/")
_REQUIREMENTS_FILE_RE = re.compile(r"^.+\.(?:txt|cfg|toml|in)$")

_PIP_FLAGS_WITH_VALUE: frozenset[str] = frozenset({
    "-r", "--requirement", "-c", "--constraint", "-e", "--editable",
    "-f", "--find-links", "-i", "--index-url", "--extra-index-url",
    "--no-index", "--prefix", "--root", "--target", "-t",
})

_PIP_VERSION_SPEC_RE = re.compile(r"[>=<~!;\[]")
_NPM_VERSION_SPEC_RE = re.compile(r"@(?![\w-]+/)")

_PYPI_NORMALIZE_RE = re.compile(r"[-_.]+")

_PROBE_TIMEOUT_S = 5

_verified_packages: set[str] = set()


def _normalize_pypi_name(name: str) -> str:
    """PEP 503 normalization: underscores, dots, hyphens all become ``-``."""
    return _PYPI_NORMALIZE_RE.sub("-", name).lower()


def _strip_python_version_spec(token: str) -> str:
    parts = _PIP_VERSION_SPEC_RE.split(token, maxsplit=1)
    return parts[0]


def _strip_npm_version_spec(token: str) -> str:
    if token.startswith("@") and "/" in token:
        scope_end = token.index("/") + 1
        rest = token[scope_end:]
        parts = _NPM_VERSION_SPEC_RE.split(rest, maxsplit=1)
        return token[:scope_end] + parts[0]
    parts = _NPM_VERSION_SPEC_RE.split(token, maxsplit=1)
    return parts[0]


def _extract_pip_packages(args_str: str) -> list[str]:
    """Extract package names from pip install arguments."""
    packages: list[str] = []
    skip_next = False
    tokens = args_str.split()
    for i, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        token = token.strip("'\"")
        if token.startswith("-"):
            if token in _PIP_FLAGS_WITH_VALUE:
                skip_next = i + 1 < len(tokens)
            continue
        if any(token.startswith(prefix) for prefix in _LOCAL_PACKAGE_PREFIXES):
            continue
        if _REQUIREMENTS_FILE_RE.match(token):
            continue
        name = _strip_python_version_spec(token)
        if name:
            packages.append(name)
    return packages


def _extract_npm_packages(args_str: str) -> list[str]:
    """Extract package names from npm/pnpm/yarn/bun install arguments."""
    packages: list[str] = []
    for token in args_str.split():
        token = token.strip("'\"")
        if token.startswith("-"):
            continue
        if any(token.startswith(prefix) for prefix in _LOCAL_PACKAGE_PREFIXES):
            continue
        name = _strip_npm_version_spec(token)
        if name:
            packages.append(name)
    return packages


async def _probe_registry(package: str, url: str, cache_key: str) -> tuple[str, bool]:
    """HEAD-probe a registry URL. Returns (package_name, exists).

    Network errors gracefully fallback to ``exists=True`` so the install is not blocked.
    """
    if cache_key in _verified_packages:
        return package, True

    try:
        loop = asyncio.get_running_loop()
        request = urllib.request.Request(url, headers={"User-Agent": "myrm-slopcheck"}, method="HEAD")
        response = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(request, timeout=_PROBE_TIMEOUT_S)
        )
        exists = response.status == 200
    except urllib.error.HTTPError as exc:
        exists = exc.code != 404
    except (urllib.error.URLError, TimeoutError, OSError):
        return package, True

    if exists:
        _verified_packages.add(cache_key)
    return package, exists


def _probe_pypi(package: str) -> asyncio.Task[tuple[str, bool]]:
    normalized = _normalize_pypi_name(package)
    return asyncio.create_task(
        _probe_registry(package, f"https://pypi.org/pypi/{normalized}/json", f"pypi:{normalized}")
    )


def _probe_npm(package: str) -> asyncio.Task[tuple[str, bool]]:
    return asyncio.create_task(
        _probe_registry(package, f"https://registry.npmjs.org/{package}", f"npm:{package}")
    )


async def check_install_packages(command: str) -> None:
    """Verify that packages in install commands exist on public registries.

    Blocks commands that attempt to install non-existent packages, preventing
    both wasted time on failed installs and potential slopsquatting attacks
    where LLM-hallucinated package names may be registered with malicious payloads.

    Raises:
        ToolError: If any package does not exist on its respective registry.
    """
    if _PRIVATE_REGISTRY_RE.search(command):
        return

    command = command.replace("\\\n", " ")

    pip_packages: list[str] = []
    npm_packages: list[str] = []

    for match in _PIP_INSTALL_RE.finditer(command):
        pip_packages.extend(_extract_pip_packages(match.group(1)))
    for match in _UV_ADD_RE.finditer(command):
        pip_packages.extend(_extract_pip_packages(match.group(1)))

    for match in _NPM_INSTALL_RE.finditer(command):
        npm_packages.extend(_extract_npm_packages(match.group(1)))
    for match in _YARN_ADD_RE.finditer(command):
        npm_packages.extend(_extract_npm_packages(match.group(1)))
    for match in _BUN_ADD_RE.finditer(command):
        npm_packages.extend(_extract_npm_packages(match.group(1)))

    if not pip_packages and not npm_packages:
        return

    tasks: list[asyncio.Task[tuple[str, bool]]] = []
    for pkg in pip_packages:
        tasks.append(_probe_pypi(pkg))
    for pkg in npm_packages:
        tasks.append(_probe_npm(pkg))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    missing: list[tuple[str, str]] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        name, exists = result
        if not exists:
            registry = "PyPI" if name in pip_packages else "npm"
            missing.append((name, registry))

    if missing:
        from myrm_agent_harness.utils.errors import ToolError

        details = "; ".join(f"'{name}' not found on {reg}" for name, reg in missing)
        logger.warning("Slopcheck blocked install: %s (command: %s)", details, command[:120])
        raise ToolError(
            f"Package verification failed: {details}. "
            "Please verify the package name(s) — AI models sometimes hallucinate non-existent packages.",
            user_hint=f"The following packages do not exist: {details}. "
            "Double-check the package name or search the registry for the correct one.",
        )
