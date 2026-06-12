"""Architecture gate: toolkits/ must not import agent/.

See toolkits/_ARCH.md forbidden dependencies. Violations break the
framework-agnostic toolkit contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

HARNESS_ROOT = Path(__file__).resolve().parents[2]
TOOLKITS_ROOT = HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits"
AGENT_PREFIX = "myrm_agent_harness.agent"


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


@pytest.mark.architecture
def test_toolkits_do_not_import_agent() -> None:
    violations: list[str] = []
    for py_file in sorted(TOOLKITS_ROOT.rglob("*.py")):
        rel = py_file.relative_to(HARNESS_ROOT)
        for lineno, module in _collect_imports(py_file):
            if module == AGENT_PREFIX or module.startswith(f"{AGENT_PREFIX}."):
                violations.append(f"{rel}:{lineno} imports {module}")
    if violations:
        message = "toolkits→agent boundary violations:\n" + "\n".join(violations)
        raise AssertionError(message)
