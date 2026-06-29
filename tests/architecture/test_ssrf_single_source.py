"""Architecture gate: SSRF validation must live in core/security/guards only."""

from __future__ import annotations

import ast
from pathlib import Path

_HARNESS_SRC = Path(__file__).resolve().parents[3] / "src" / "myrm_agent_harness"

_FORBIDDEN_SSRF_PATTERNS = (
    "validate_url_for_ssrf",
    "async_validate_url_for_ssrf",
    "validate_and_resolve_url",
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


def test_toolkits_network_package_removed() -> None:
    network_dir = _HARNESS_SRC / "toolkits" / "network"
    assert not network_dir.exists(), "toolkits/network/ must not exist — use core/security/guards/ssrf.py"
