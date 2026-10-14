"""The browser facade has two views of its lazy exports; they must agree.

At runtime ``__getattr__`` resolves a symbol through ``_LAZY_MODULES``. A type checker only sees the
``if TYPE_CHECKING`` imports, so a symbol missing there is typed as ``object`` for every caller.
"""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

import pytest

import myrm_agent_harness.toolkits.browser as browser

_PACKAGE = browser.__name__
_LAZY: dict[str, list[str]] = browser._LAZY_MODULES


def _static_imports() -> dict[str, str]:
    """Symbol -> relative module, from the ``if TYPE_CHECKING`` block of the facade."""
    tree = ast.parse(Path(browser.__file__).read_text(encoding="utf-8"))
    imports: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            for stmt in node.body:
                if isinstance(stmt, ast.ImportFrom) and stmt.level == 1 and stmt.module:
                    imports.update({alias.name: stmt.module for alias in stmt.names})
    return imports


def _lazy_symbols() -> dict[str, str]:
    return {symbol: module for module, symbols in _LAZY.items() for symbol in symbols}


def test_every_lazy_symbol_is_visible_to_type_checkers() -> None:
    missing = sorted(set(_lazy_symbols()) - set(_static_imports()))
    assert not missing, f"lazy exports absent from the TYPE_CHECKING imports (typed as object): {missing}"


def test_no_static_import_is_left_without_a_lazy_entry() -> None:
    stale = sorted(set(_static_imports()) - set(_lazy_symbols()))
    assert not stale, f"TYPE_CHECKING imports with no lazy entry (unreachable at runtime): {stale}"


@pytest.mark.parametrize("symbol", sorted(_lazy_symbols()))
def test_static_and_lazy_views_resolve_to_the_same_object(symbol: str) -> None:
    static_module = _static_imports().get(symbol)
    assert static_module is not None, f"{symbol} has no TYPE_CHECKING import"
    from_static = getattr(import_module(f".{static_module}", _PACKAGE), symbol)
    from_lazy = getattr(import_module(f".{_lazy_symbols()[symbol]}", _PACKAGE), symbol)
    assert from_static is from_lazy
    assert getattr(browser, symbol) is from_lazy


def test_every_public_name_resolves() -> None:
    unresolved = [name for name in browser.__all__ if not hasattr(browser, name)]
    assert not unresolved
