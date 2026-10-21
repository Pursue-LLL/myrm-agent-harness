"""Parity of the ``toolkits`` lazy registry with its static ``TYPE_CHECKING`` mirror.

[INPUT]
- myrm_agent_harness.toolkits: ``_LAZY_IMPORTS`` registry and the ``TYPE_CHECKING`` import block

[OUTPUT]
- A failing assertion when a lazily exported name has no real type for static checkers (or the reverse).

[POS]
Cross-toolkit guard: type checkers see ``object`` for every name the ``__getattr__`` fallback resolves.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path


def _type_checking_imports(module_source: str) -> dict[str, tuple[str, str]]:
    tree = ast.parse(module_source)
    guards = [
        node for node in tree.body if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING"
    ]
    return {
        alias.name: (stmt.module, alias.name)
        for guard in guards
        for stmt in guard.body
        if isinstance(stmt, ast.ImportFrom) and stmt.module
        for alias in stmt.names
    }


def test_type_checking_block_mirrors_lazy_registry() -> None:
    toolkits = importlib.import_module("myrm_agent_harness.toolkits")
    source = Path(toolkits.__file__).read_text(encoding="utf-8")

    assert _type_checking_imports(source) == toolkits._LAZY_IMPORTS
