"""Per-file evidence for the module-reachability engine.

Evidence is expressed as fully-qualified dotted references. A file yields the references it
really uses: imported module paths, names bound by an import and then loaded, attribute chains on
imported modules, dotted-path strings and ``module:attr`` strings, plus the names a hub
(``__init__.py``) re-exports so the engine can follow a name through the hub.

Facade rule: in a hub, ``from .x import Y`` imports, ``X = Y`` aliases and lazy
``{"Name": ("module", "attr")}`` tables are re-exports, not uses; only real uses (calls, attribute
access) and bare ``import a.b.c`` statements count. A bare import binds no name a hub could
re-export, so its only purpose is to run the module for its side effects (registration).
``api/`` and the package root ``__init__.py`` are the public surface and count like ordinary modules.
A bare identifier that merely equals an exported name never counts.
"""

from __future__ import annotations

import ast
import re
import warnings
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

_DOTTED: Final = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")


class Role(Enum):
    """How a file's imports are weighed as evidence."""

    MODULE = "module"  # ordinary file: imports, strings and uses all count
    HUB = "hub"  # facade __init__: only real uses and bare imports count; re-exports become bindings
    SURFACE = "surface"  # public-surface __init__: counts like a module and exposes bindings


@dataclass(frozen=True)
class FileFacts:
    """Static evidence extracted from one Python file."""

    targets: frozenset[str]
    bindings: Mapping[str, str]
    exports: frozenset[str]
    lines: int


def _resolve_relative(level: int, module: str | None, package: str) -> str:
    if level == 0:
        return module or ""
    base = package.split(".") if package else []
    if level > 1:
        base = base[: max(len(base) - (level - 1), 0)]
    return ".".join([*base, *([module] if module else [])])


def _module_statements(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    """Statements executed at import time: module level plus ``if`` / ``try`` / ``with`` blocks."""
    for node in body:
        yield node
        if isinstance(node, ast.If | ast.Try | ast.With):
            blocks = [node.body, getattr(node, "orelse", []), getattr(node, "finalbody", [])]
            blocks.extend(handler.body for handler in getattr(node, "handlers", []))
            for block in blocks:
                yield from _module_statements(block)


def _exports(tree: ast.Module) -> frozenset[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(
                t.id for t in targets if isinstance(t, ast.Name) and t.id.isupper() and not t.id.startswith("_")
            )
    return frozenset(names)


def _import_bindings(nodes: Iterable[ast.AST], package: str) -> tuple[dict[str, str], set[str]]:
    """Return ``(local name -> dotted target, dotted modules and members imported)``."""
    bound: dict[str, str] = {}
    imported: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
                top = alias.name.split(".")[0]
                bound[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative(node.level, node.module, package)
            if not base:
                continue
            for alias in node.names:
                imported.add(base if alias.name == "*" else f"{base}.{alias.name}")
                if alias.name != "*":
                    bound[alias.asname or alias.name] = f"{base}.{alias.name}"
    return bound, imported


def _bare_imports(nodes: Iterable[ast.Import | ast.ImportFrom]) -> set[str]:
    """Modules named by ``import a.b.c`` statements that bind no alias."""
    return {
        alias.name for node in nodes if isinstance(node, ast.Import) for alias in node.names if alias.asname is None
    }


def _chain(node: ast.expr) -> tuple[ast.expr, list[ast.Attribute]]:
    """Split ``a.b.c`` into its head (``a``) and the attribute links, outermost first."""
    links: list[ast.Attribute] = []
    while isinstance(node, ast.Attribute):
        links.append(node)
        node = node.value
    return node, links


def _expand(head: ast.expr, links: Sequence[ast.Attribute], bound: Mapping[str, str]) -> str | None:
    if isinstance(head, ast.Name) and head.id in bound:
        return ".".join([bound[head.id], *(link.attr for link in reversed(links))])
    return None


def _prefixes(roots: Sequence[str]) -> tuple[str, ...]:
    return tuple(f"{root}." for root in roots)


@dataclass(frozen=True)
class _Scan:
    """The nodes that carry evidence, collected in one pass; ``loads`` keeps parent-before-child order."""

    imports: tuple[ast.Import | ast.ImportFrom, ...]
    loads: tuple[ast.Name | ast.Attribute, ...]
    strings: tuple[str, ...]
    dicts: tuple[ast.Dict, ...]


def _scan(tree: ast.Module, roots: Sequence[str], *, want_dicts: bool) -> _Scan:
    imports: list[ast.Import | ast.ImportFrom] = []
    loads: list[ast.Name | ast.Attribute] = []
    strings: list[str] = []
    dicts: list[ast.Dict] = []
    prefixes = _prefixes(roots)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name | ast.Attribute):
            if isinstance(node.ctx, ast.Load):
                loads.append(node)
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, str) and node.value.startswith(prefixes):
                strings.append(node.value)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            imports.append(node)
        elif want_dicts and isinstance(node, ast.Dict):
            dicts.append(node)
    return _Scan(tuple(imports), tuple(loads), tuple(strings), tuple(dicts))


def _used_targets(loads: Iterable[ast.Name | ast.Attribute], bound: Mapping[str, str], skip: set[int]) -> set[str]:
    """Dotted references of loads rooted at an imported name; attribute chains are kept whole."""
    used: set[str] = set()
    done = set(skip)
    for node in loads:
        if id(node) in done:
            continue
        if isinstance(node, ast.Attribute):
            head, links = _chain(node)
            done.update(id(link) for link in links)
            done.add(id(head))
            if target := _expand(head, links, bound):
                used.add(target)
        elif node.id in bound:
            used.add(bound[node.id])
    return used


def _string_module(value: str, package: str, roots: Sequence[str]) -> str:
    """Absolute dotted module named by an import-path string, or ``""``."""
    if value.startswith("."):
        stripped = value.lstrip(".")
        return _resolve_relative(len(value) - len(stripped), stripped or None, package)
    return value if value.startswith(_prefixes(roots)) and _DOTTED.match(value) else ""


def _string_targets(strings: Iterable[str]) -> set[str]:
    """``root.pkg.mod`` and ``root.pkg.mod:attr`` strings (importlib / entry-point style references)."""
    found: set[str] = set()
    for value in strings:
        module, sep, attr = value.partition(":")
        if _DOTTED.match(module) and (not sep or all(part.isidentifier() for part in attr.split("."))):
            found.add(f"{module}.{attr}" if sep else module)
    return found


def _lazy_table(dicts: Iterable[ast.Dict], package: str, roots: Sequence[str]) -> dict[str, str]:
    """Lazy hub tables ``{"Name": ("module", "attr")}`` as ``name -> dotted target``."""
    table: dict[str, str] = {}
    for node in dicts:
        for key, value in zip(node.keys, node.values, strict=True):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if not (isinstance(value, ast.Tuple | ast.List) and len(value.elts) == 2):
                continue
            parts = [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            module = _string_module(parts[0], package, roots) if len(parts) == 2 else ""
            if module and parts[1].isidentifier():
                table[key.value] = f"{module}.{parts[1]}"
    return table


def _hub_bindings(tree: ast.Module, scan: _Scan, package: str, roots: Sequence[str]) -> tuple[dict[str, str], set[int]]:
    """Names a hub re-exports and the AST node ids of its alias right-hand sides."""
    statements = list(_module_statements(tree.body))
    bound, _ = _import_bindings((n for n in statements if isinstance(n, ast.Import | ast.ImportFrom)), package)
    bindings = {**bound, **_lazy_table(scan.dicts, package, roots)}
    aliased: set[int] = set()
    for node in statements:
        if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(node.value, ast.Name | ast.Attribute):
            aliased.update(id(child) for child in ast.walk(node.value))
            head, links = _chain(node.value)
            if (target := _expand(head, links, bound)) and isinstance(node, ast.Assign):
                bindings.update({t.id: target for t in node.targets if isinstance(t, ast.Name)})
    return bindings, aliased


def analyze_source(text: str, package: str, roots: Sequence[str], *, role: Role) -> FileFacts:
    """Extract evidence from ``text``.

    ``package`` is the dotted package the file lives in; ``roots`` are the top-level package names
    whose dotted-path strings count as references.
    """
    lines = text.count("\n") + 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return FileFacts(frozenset(), {}, frozenset(), lines)

    scan = _scan(tree, roots, want_dicts=role is not Role.MODULE)
    bound, imported = _import_bindings(scan.imports, package)
    bindings: dict[str, str] = {}
    aliased: set[int] = set()
    if role is not Role.MODULE:
        bindings, aliased = _hub_bindings(tree, scan, package, roots)
    targets = _used_targets(scan.loads, bound, aliased)
    if role is Role.HUB:
        targets |= _bare_imports(scan.imports)
    else:
        targets |= imported | _string_targets(scan.strings) | set(bindings.values())
    return FileFacts(frozenset(targets), bindings, _exports(tree), lines)
