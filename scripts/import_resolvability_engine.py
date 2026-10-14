"""Static engine behind the import-resolvability gate.

A first-party import is *resolvable* when the module it names exists under one of the
package roots and, for ``from M import N``, ``N`` is a submodule of ``M`` or a name ``M``
binds at import time: a class, function, assignment, loop or ``with`` target, import
binding, ``__all__`` entry, or a name re-exported through ``from X import *``. A module that
assembles its namespace dynamically (module-level ``__getattr__`` or ``globals()``
mutation) accepts every name, so the gate never reports a name it cannot disprove.

Imports are checked wherever they occur - module level, inside functions, ``try`` blocks
and ``TYPE_CHECKING`` guards - because the failures this gate exists for sit in lazy imports
wrapped in ``except Exception`` that no test executes and no type checker is configured to
resolve. Imports of modules outside the given roots (stdlib, third party) are out of scope.
"""

from __future__ import annotations

import ast
import warnings
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

MODULE_MISSING: Final = "module not found"
NAME_MISSING: Final = "name not defined"

# A module that rewrites its own namespace at runtime cannot be enumerated statically.
_DYNAMIC_MARKERS: Final = ("globals()", "sys.modules[__name__]")
_NESTED_BLOCKS: Final = ("body", "orelse", "finalbody")


@dataclass(frozen=True, slots=True)
class Finding:
    """One import that does not resolve."""

    path: Path
    line: int
    target: str
    reason: str


@dataclass(frozen=True, slots=True)
class Report:
    findings: tuple[Finding, ...]
    unparsable: tuple[Path, ...]
    files_scanned: int
    imports_checked: int


@dataclass(frozen=True, slots=True)
class _Symbols:
    names: frozenset[str]
    stars: tuple[str, ...]
    exported: frozenset[str] | None
    dynamic: bool


# Stand-in for a file that cannot be parsed: it still exists as a module, but none of its names can be disproved.
_UNPARSED_SYMBOLS: Final = _Symbols(names=frozenset(), stars=(), exported=None, dynamic=True)


@dataclass(frozen=True, slots=True)
class _ImportRef:
    line: int
    module: str
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Module:
    path: Path
    symbols: _Symbols
    imports: tuple[_ImportRef, ...]


def _python_files(root: Path) -> Iterable[Path]:
    return (path for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts)


def _resolve_relative(level: int, module: str | None, package: str) -> str:
    if level == 0:
        return module or ""
    base = package.split(".") if package else []
    if level > 1:
        base = base[: max(len(base) - (level - 1), 0)]
    return ".".join([*base, *([module] if module else [])])


def _import_time_statements(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    """Statements that run at import: module level plus nested blocks, never ``def`` / ``class`` bodies."""
    for node in body:
        yield node
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        for field in _NESTED_BLOCKS:
            yield from _import_time_statements(getattr(node, field, ()))
        for handler in getattr(node, "handlers", ()):
            yield from _import_time_statements(handler.body)
        for case in getattr(node, "cases", ()):
            yield from _import_time_statements(case.body)


def _bound_names(target: ast.expr) -> Iterator[str]:
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, ast.Tuple | ast.List):
        for element in target.elts:
            yield from _bound_names(element)
    elif isinstance(target, ast.Starred):
        yield from _bound_names(target.value)


def _string_items(value: ast.expr | None) -> list[str] | None:
    """Items of a literal list/tuple of strings; ``None`` when the value is computed."""
    if not isinstance(value, ast.List | ast.Tuple):
        return None
    items: list[str] = []
    for element in value.elts:
        if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
            return None
        items.append(element.value)
    return items


def _fold_all(node: ast.stmt, exported: set[str] | None) -> set[str] | None:
    """Fold ``__all__ = [...]`` / ``__all__ += [...]`` into the running export set."""
    value: ast.expr | None
    if isinstance(node, ast.Assign):
        targets, value = node.targets, node.value
    elif isinstance(node, ast.AnnAssign | ast.AugAssign):
        targets, value = [node.target], node.value
    else:
        return exported
    if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
        return exported
    items = _string_items(value)
    if items is None:
        return exported
    return (exported or set()) | set(items) if isinstance(node, ast.AugAssign) else set(items)


def _statement_names(node: ast.stmt) -> Iterator[str]:
    """Names a non-import statement binds in the module namespace."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        yield node.name
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            yield from _bound_names(target)
    elif isinstance(node, ast.AnnAssign):
        if node.value is not None:
            yield from _bound_names(node.target)
    elif isinstance(node, ast.TypeAlias):
        yield from _bound_names(node.name)
    elif isinstance(node, ast.For | ast.AsyncFor):
        yield from _bound_names(node.target)
    elif isinstance(node, ast.With | ast.AsyncWith):
        for item in node.items:
            if item.optional_vars is not None:
                yield from _bound_names(item.optional_vars)


def _collect_symbols(tree: ast.Module, text: str, package: str) -> _Symbols:
    names: set[str] = set()
    stars: list[str] = []
    exported: set[str] | None = None
    dynamic = any(marker in text for marker in _DYNAMIC_MARKERS)
    for node in _import_time_statements(tree.body):
        names.update(_statement_names(node))
        exported = _fold_all(node, exported)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "__getattr__":
            dynamic = True
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative(node.level, node.module, package)
            for alias in node.names:
                if alias.name == "*":
                    stars.append(base)
                else:
                    names.add(alias.asname or alias.name)
    return _Symbols(
        names=frozenset(names),
        stars=tuple(stars),
        exported=None if exported is None else frozenset(exported),
        dynamic=dynamic,
    )


def _collect_imports(tree: ast.Module, package: str) -> tuple[_ImportRef, ...]:
    refs: list[_ImportRef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs.extend(_ImportRef(node.lineno, alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_relative(node.level, node.module, package)
            if module:
                names = tuple(alias.name for alias in node.names if alias.name != "*")
                refs.append(_ImportRef(node.lineno, module, names))
    return tuple(refs)


def _parse(path: Path) -> tuple[ast.Module, str] | None:
    try:
        text = path.read_text(encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(text, filename=str(path)), text
    except (OSError, SyntaxError, ValueError, RecursionError):
        return None


class _Index:
    """Every module under the roots, with its import-time symbols (and imports when scanned)."""

    def __init__(self, roots: Mapping[str, Path], scanned: frozenset[str]) -> None:
        self.modules: dict[str, _Module] = {}
        self.namespaces: set[str] = set(roots)
        self.unparsable: list[Path] = []
        self.files_scanned = 0
        for root_name, root in roots.items():
            self._load(root_name, root, scanned=root_name in scanned)

    def _load(self, root_name: str, root: Path, *, scanned: bool) -> None:
        for path in _python_files(root):
            parts = path.relative_to(root).with_suffix("").parts
            package_parts = parts[:-1]
            is_init = parts[-1] == "__init__"
            module = ".".join([root_name, *(package_parts if is_init else parts)])
            package = ".".join([root_name, *package_parts])
            parsed = _parse(path)
            if parsed is None:
                self.unparsable.append(path)
                self.modules[module] = _Module(path, _UNPARSED_SYMBOLS, ())
            else:
                tree, text = parsed
                if scanned:
                    self.files_scanned += 1
                imports = _collect_imports(tree, package) if scanned else ()
                self.modules[module] = _Module(path, _collect_symbols(tree, text, package), imports)
            self.namespaces.update(
                ".".join([root_name, *package_parts[:depth]]) for depth in range(1, len(package_parts) + 1)
            )

    def exists(self, module: str) -> bool:
        return module in self.modules or module in self.namespaces

    def defines(self, module: str, name: str, seen: frozenset[str] = frozenset()) -> bool:
        """Whether ``from module import name`` succeeds (leniently: unknown dynamics count as defined)."""
        qualified = f"{module}.{name}"
        if qualified in self.modules or qualified in self.namespaces:
            return True
        info = self.modules.get(module)
        if info is None or module in seen:
            return False
        symbols = info.symbols
        if symbols.dynamic or name in symbols.names or (symbols.exported is not None and name in symbols.exported):
            return True
        visited = seen | {module}
        return any(self._star_exports(star, name, visited) for star in symbols.stars)

    def _star_exports(self, star: str, name: str, seen: frozenset[str]) -> bool:
        target = self.modules.get(star)
        if target is None:
            return False
        if target.symbols.exported is not None:
            return name in target.symbols.exported
        return not name.startswith("_") and self.defines(star, name, seen)


def analyze(roots: Mapping[str, Path], scan: Iterable[str] | None = None) -> Report:
    """Check every first-party import of the ``scan`` roots (default: all) against all ``roots``.

    ``roots`` maps a top-level package name to its directory; only imports whose first segment
    is one of those names are evaluated.
    """
    index = _Index(roots, frozenset(roots if scan is None else scan))
    findings: list[Finding] = []
    checked = 0
    for module in index.modules.values():
        for ref in module.imports:
            if ref.module.split(".", 1)[0] not in roots:
                continue
            checked += 1
            if not index.exists(ref.module):
                findings.append(Finding(module.path, ref.line, ref.module, MODULE_MISSING))
                continue
            findings.extend(
                Finding(module.path, ref.line, f"{ref.module}:{name}", NAME_MISSING)
                for name in ref.names
                if not index.defines(ref.module, name)
            )
    findings.sort(key=lambda finding: (str(finding.path), finding.line, finding.target))
    return Report(
        findings=tuple(findings),
        unparsable=tuple(sorted(index.unparsable)),
        files_scanned=index.files_scanned,
        imports_checked=checked,
    )
