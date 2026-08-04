"""Security preflight checks for bash command execution.

[INPUT]
utils.url_utils::check_url_exfiltration, sanitize_url_for_error (POS: URL security validation)
utils.errors::ToolError (POS: Agent tool error with format_for_llm protocol)

[OUTPUT]
check_command_url_exfiltration: Block commands with URL data exfiltration.
check_sensitive_paths: Block commands accessing sensitive directories.
check_myrm_tools_import: Block myrm_tools in bash via AST, shell `-c`, `-m`, pipe stdin, cat|pipe `.py`, and referenced `.py` files.
check_interactive_command: Detect commands requiring interactive stdin.
check_install_packages: Verify install package names exist on public registries.

[POS]
Security preflight for bash commands. Validates URLs against data exfiltration,
blocks access to sensitive paths (.ssh, .aws, etc.), blocks myrm_tools in bash (command AST,
referenced script files under workspace), detects interactive commands that would hang in a non-TTY environment, and verifies
package names in install commands against public registries (anti-slopsquatting).
"""

from __future__ import annotations

import ast
import asyncio
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# myrm_tools guard (bash only; Dynamic Workflow inject_ptc is separate)
# ---------------------------------------------------------------------------

_SHELL_MYRM_TOOLS_IMPORT_RE = re.compile(
    r"(?:^|\n)\s*(?:import\s+myrm_tools\b|from\s+myrm_tools\s+import\b)",
    re.MULTILINE,
)

_SHELL_C_CMD_RE = re.compile(
    r"(?:^|[\s;&|])(?:bash|sh|/bin/bash|/bin/sh)\s+(?:-[^\s]+\s+)*-c\s+",
    re.MULTILINE,
)

_PYTHON_SCRIPT_INVOCATION_RE = re.compile(
    r"(?:^|[\s;&|])python3?(?:\s+-[^\s]+)*\s+([^\s;&|]+\.py)\b",
    re.IGNORECASE | re.MULTILINE,
)

_PYTHON_M_MYRM_TOOLS_RE = re.compile(
    r"\bpython3?\s+(?:-[^\s]+\s+)*-m\s+myrm_tools(?:[.\s]|$)",
    re.IGNORECASE,
)

_MAX_REFERENCED_PY_SCAN_BYTES = 512 * 1024

_MYRM_TOOLS_BLOCK_MESSAGE = (
    "Command blocked: `import myrm_tools` is not available in bash_code_execute_tool. "
    "Use native tools for single calls; use `from skills.* import ...` or "
    "`from tools.* import ...` for MCP/builtin batch scripts; "
    "use `from tools.session_store import session_store` for cross-call persistence."
)
_MYRM_TOOLS_BLOCK_HINT = (
    "Do not use myrm_tools in bash. Single calls: native tools "
    "(file_read_tool, web_search_tool, …). MCP batch: from skills.* import …. "
    "Cross-bash data: tools.session_store. Long-script progress: MYRM_PROGRESS echo."
)


def _ast_root_name(node: ast.AST) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None


def _extract_shell_c_payload(command: str) -> str | None:
    """Quote-aware extraction from ``bash -c`` / ``sh -c`` inline scripts."""
    match = _SHELL_C_CMD_RE.search(command)
    if match is None:
        return None

    rest = command[match.end() :]
    if not rest:
        return None

    quote = rest[0]
    if quote not in ('"', "'"):
        return None

    escaped = False
    for index, char in enumerate(rest[1:], start=1):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == quote:
            return rest[1:index]
    return None


def _shell_command_references_myrm_tools(command: str) -> bool:
    if _SHELL_MYRM_TOOLS_IMPORT_RE.search(command):
        return True
    shell_c_payload = _extract_shell_c_payload(command)
    if shell_c_payload is None:
        return False
    return _python_ast_references_myrm_tools(shell_c_payload) or bool(
        _SHELL_MYRM_TOOLS_IMPORT_RE.search(shell_c_payload)
    )


def _python_ast_references_myrm_tools(code: str) -> bool:
    """Return True when parsed Python references the ``myrm_tools`` namespace."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] == "myrm_tools":
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".", 1)[0] == "myrm_tools":
                return True
        elif isinstance(node, ast.Attribute) and _ast_root_name(node) == "myrm_tools":
            return True
    return False


def _raise_myrm_tools_blocked(command: str) -> None:
    from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
    from myrm_agent_harness.utils.errors import ToolError

    logger.warning("Blocked myrm_tools reference in bash command: %s", command[:120])
    raise ToolError(
        _MYRM_TOOLS_BLOCK_MESSAGE,
        user_hint=_MYRM_TOOLS_BLOCK_HINT,
        error_code="MYRM_TOOLS_BLOCKED",
        diagnostic_info={"error_category": ToolErrorCategory.GUARDRAIL_BLOCKED.value},
    )


def _scan_python_file_path(script_path: Path, command: str) -> None:
    if not script_path.is_file():
        return
    if script_path.stat().st_size > _MAX_REFERENCED_PY_SCAN_BYTES:
        logger.warning(
            "Skipping myrm_tools scan for oversized script reference: %s",
            script_path,
        )
        return
    try:
        source = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Unable to read referenced python script %s: %s", script_path, exc)
        return
    if _python_ast_references_myrm_tools(source):
        _raise_myrm_tools_blocked(command)


def _command_runs_myrm_tools_module(command: str) -> bool:
    return _PYTHON_M_MYRM_TOOLS_RE.search(command) is not None


def _extract_referenced_python_scripts(command: str) -> list[str]:
    return list(dict.fromkeys(_PYTHON_SCRIPT_INVOCATION_RE.findall(command)))


def _resolve_referenced_python_path(script_ref: str, workspace_root: str | None) -> Path | None:
    from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
        WorkspacePathResolver,
    )

    cleaned = script_ref.strip().strip("'\"")
    if not cleaned.endswith(".py"):
        return None

    if cleaned.startswith("/workspace"):
        local_path = WorkspacePathResolver.to_local_path(cleaned, workspace_root)
        return local_path.resolve() if local_path is not None else None

    if cleaned.startswith("/"):
        if not workspace_root:
            return None
        candidate = Path(cleaned)
        if not candidate.is_absolute():
            return None
        resolved = candidate.resolve()
        root = Path(workspace_root).resolve()
        if root not in resolved.parents and resolved != root:
            return None
        return resolved

    if workspace_root:
        return (Path(workspace_root).resolve() / cleaned).resolve()

    container_path = f"/workspace/{cleaned.lstrip('./')}"
    local_path = WorkspacePathResolver.to_local_path(container_path, None)
    return local_path.resolve() if local_path is not None else None


def _scan_referenced_python_files(command: str, workspace_root: str | None) -> None:
    for script_ref in _extract_referenced_python_scripts(command):
        script_path = _resolve_referenced_python_path(script_ref, workspace_root)
        if script_path is None:
            continue
        _scan_python_file_path(script_path, command)


def _scan_cat_pipe_feeder_python_files(command: str, workspace_root: str | None) -> None:
    from myrm_agent_harness.toolkits.code_execution.python_extractor import (
        extract_cat_py_paths_from_pipe_feeders,
    )

    for script_ref in extract_cat_py_paths_from_pipe_feeders(command):
        script_path = _resolve_referenced_python_path(script_ref, workspace_root)
        if script_path is None:
            continue
        _scan_python_file_path(script_path, command)


def check_myrm_tools_import(command: str, *, workspace_root: str | None = None) -> None:
    """Block ``myrm_tools`` in bash — reserved for Dynamic Workflow inject_ptc only.

    Python snippets: AST inspects imports and attribute access.
    Shell commands: line-leading ``import`` / ``from myrm_tools import``, plus
    ``bash|sh -c '…'`` inline payloads, ``quoted | python3`` stdin payloads,
    ``python -m myrm_tools``, ``cat *.py | python3`` feeder scans,
    and ``python *.py`` references scan file AST.
    Incidental ``myrm_tools`` in ``echo``/``grep`` allowed.

    Raises:
        ToolError: If command references ``myrm_tools`` in an executable Python path.
    """
    from myrm_agent_harness.toolkits.code_execution.code_detector import CodeType, code_detector

    detection = code_detector.detect(command)
    code = detection.extracted_code if detection.code_type == CodeType.PYTHON else command

    if _python_ast_references_myrm_tools(code):
        _raise_myrm_tools_blocked(command)
        return

    if _command_runs_myrm_tools_module(command):
        _raise_myrm_tools_blocked(command)
        return

    if detection.code_type == CodeType.BASH and _shell_command_references_myrm_tools(command):
        _raise_myrm_tools_blocked(command)
        return

    from myrm_agent_harness.toolkits.code_execution.python_extractor import (
        extract_python_from_pipe_stdin,
    )

    pipe_stdin_code = extract_python_from_pipe_stdin(command)
    if pipe_stdin_code is not None and _python_ast_references_myrm_tools(pipe_stdin_code):
        _raise_myrm_tools_blocked(command)
        return

    _scan_cat_pipe_feeder_python_files(command, workspace_root)
    _scan_referenced_python_files(command, workspace_root)


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
