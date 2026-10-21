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
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES)


def _collect_string_references(py_file: Path) -> list[tuple[int, str]]:
    """Find forbidden layer references hiding in dynamic import calls.

    Catches ``importlib.import_module("myrm_agent_harness.agent...")`` style
    dynamic imports that AST import-node scanning cannot see. Only string
    literals passed as the module argument of a ``*import_module`` / ``__import__``
    call are flagged; docstrings and comments are ignored.
    """
    references: list[tuple[int, str]] = []
    try:
        text = py_file.read_text(encoding="utf-8")
    except OSError:
        return references
    tree = ast.parse(text, filename=str(py_file))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        is_import_call = (isinstance(func, ast.Name) and func.id == "__import__") or (
            isinstance(func, ast.Attribute) and func.attr in {"import_module", "__import__"}
        )
        if not is_import_call:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            for prefix in FORBIDDEN_PREFIXES:
                if first_arg.value == prefix or first_arg.value.startswith(f"{prefix}."):
                    references.append((node.lineno, first_arg.value))
    return references


@pytest.mark.architecture
def test_toolkits_do_not_import_forbidden_layers() -> None:
    violations: list[str] = []
    for py_file in sorted(TOOLKITS_ROOT.rglob("*.py")):
        rel = py_file.relative_to(HARNESS_ROOT)
        for lineno, module in _collect_imports(py_file):
            if _matches_forbidden(module):
                violations.append(f"{rel}:{lineno} imports {module}")
        for lineno, reference in _collect_string_references(py_file):
            violations.append(f"{rel}:{lineno} dynamic-imports {reference}")
    if violations:
        msg = "toolkits/ forbidden dependency violations:\n" + "\n".join(violations)
        raise AssertionError(msg)
