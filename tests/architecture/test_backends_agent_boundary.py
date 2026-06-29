"""Architecture gate: backends/ must not import agent/ at module level.

Lazy imports inside function bodies are allowed for optional integration paths.
Module-level imports break the storage-adapter layer contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

HARNESS_ROOT = Path(__file__).resolve().parents[2]
BACKENDS_ROOT = HARNESS_ROOT / "src" / "myrm_agent_harness" / "backends"

FORBIDDEN_PREFIX = "myrm_agent_harness.agent"


def _is_type_checking(node: ast.If) -> bool:
    test = node.test
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


def _append_imports(node: ast.Import | ast.ImportFrom, imports: list[tuple[int, str]]) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            imports.append((node.lineno, alias.name))
    elif node.module:
        imports.append((node.lineno, node.module))


def _collect_module_level_imports(tree: ast.Module) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            _append_imports(node, imports)
        elif isinstance(node, ast.If) and _is_type_checking(node):
            for sub in node.body:
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    _append_imports(sub, imports)
    return imports


def _matches_forbidden(module: str) -> bool:
    return module == FORBIDDEN_PREFIX or module.startswith(f"{FORBIDDEN_PREFIX}.")


@pytest.mark.architecture
def test_backends_do_not_import_agent_at_module_level() -> None:
    violations: list[str] = []
    for py_file in sorted(BACKENDS_ROOT.rglob("*.py")):
        rel = py_file.relative_to(HARNESS_ROOT)
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for lineno, module in _collect_module_level_imports(tree):
            if _matches_forbidden(module):
                violations.append(f"{rel}:{lineno} imports {module}")
    if violations:
        msg = "backends/ module-level agent/ import violations:\n" + "\n".join(violations)
        raise AssertionError(msg)
