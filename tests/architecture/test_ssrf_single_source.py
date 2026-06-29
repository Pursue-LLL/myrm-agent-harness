"""Architecture gate: SSRF validation must live in core/security/guards only."""

from __future__ import annotations

import ast
from pathlib import Path

_HARNESS_SRC = Path(__file__).resolve().parents[3] / "src" / "myrm_agent_harness"

_FORBIDDEN_SSRF_PATTERNS = (
    "validate_url_for_ssrf",
    "async_validate_url_for_ssrf",
    "_validate_url_security",
)

_ALLOWED_SSRF_ROOTS = (
    _HARNESS_SRC / "core" / "security" / "guards",
    _HARNESS_SRC / "utils" / "url_utils.py",
)

_SCAN_ROOTS = (
    _HARNESS_SRC / "toolkits",
    _HARNESS_SRC / "agent",
)

# Diagnostics / ops probes — not agent outbound fetch paths.
_FOLLOW_REDIRECTS_ALLOWLIST = frozenset(
    {
        "observability/diagnostics/probes.py",
        "runtime/doctor.py",
        "toolkits/web_search/local_probe.py",
        "agent/meta_tools/http/skip_upload_helper.py",
        "toolkits/mcp/client.py",
    }
)

_SSRF_IMPORT_MARKERS = (
    "secure_fetch",
    "async_pin_url",
    "validate_url_for_ssrf",
    "async_validate_url_for_ssrf",
    "resolve_secure_http_target",
    "secure_get",
    "secure_request",
)


def _defines_ssrf_helper(path: Path, tree: ast.Module) -> list[str]:
    violations: list[str] = []
    rel = path.relative_to(_HARNESS_SRC)
    if any(str(rel).startswith(allowed.relative_to(_HARNESS_SRC).as_posix()) for allowed in _ALLOWED_SSRF_ROOTS):
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if any(pattern in node.name for pattern in _FORBIDDEN_SSRF_PATTERNS):
                violations.append(f"{rel}:{node.lineno} defines {node.name}")
    return violations


def _uses_unprotected_follow_redirects(path: Path, source: str) -> bool:
    rel = path.relative_to(_HARNESS_SRC).as_posix()
    if rel in _FOLLOW_REDIRECTS_ALLOWLIST:
        return False
    if "follow_redirects=True" not in source:
        return False
    return not any(marker in source for marker in _SSRF_IMPORT_MARKERS)


def test_no_inline_ssrf_helpers_outside_core_guards() -> None:
    violations: list[str] = []
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            if path.name == "ssrf.py":
                continue
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            violations.extend(_defines_ssrf_helper(path, tree))

    assert not violations, "Inline SSRF helpers outside core/security/guards:\n" + "\n".join(violations)


def test_no_unprotected_follow_redirects_in_agent_toolkits() -> None:
    violations: list[str] = []
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            if _uses_unprotected_follow_redirects(path, source):
                rel = path.relative_to(_HARNESS_SRC)
                violations.append(f"{rel} uses follow_redirects=True without SSRF guard imports")

    assert not violations, "Unprotected follow_redirects in agent/toolkits:\n" + "\n".join(violations)


def test_toolkits_network_package_removed() -> None:
    network_dir = _HARNESS_SRC / "toolkits" / "network"
    assert not network_dir.exists(), "toolkits/network/ must not exist — use core/security/guards/ssrf.py"
