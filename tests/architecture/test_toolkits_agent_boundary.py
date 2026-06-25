"""Architecture gate: toolkits/ must not import agent/, runtime/, or backends/.

See toolkits/_ARCH.md forbidden dependencies. Violations break the
framework-agnostic toolkit contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

HARNESS_ROOT = Path(__file__).resolve().parents[2]
TOOLKITS_ROOT = HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits"

FORBIDDEN_PREFIXES = (
    "myrm_agent_harness.agent",
    "myrm_agent_harness.runtime",
    "myrm_agent_harness.backends",
)


def _collect_imports(py_file: Path) -> list[tuple[int, str]]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.lineno, node.module))
    return imports


def _matches_forbidden(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_PREFIXES
    )


@pytest.mark.architecture
def test_toolkits_do_not_import_forbidden_layers() -> None:
    violations: list[str] = []
    for py_file in sorted(TOOLKITS_ROOT.rglob("*.py")):
        rel = py_file.relative_to(HARNESS_ROOT)
        for lineno, module in _collect_imports(py_file):
            if _matches_forbidden(module):
                violations.append(f"{rel}:{lineno} imports {module}")
    if violations:
        msg = "toolkits/ forbidden dependency violations:\n" + "\n".join(violations)
        raise AssertionError(msg)
