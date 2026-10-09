"""Static engine behind the module-reachability gate.

A *unit* is a direct child (file or sub-package) of an engine directory under
``agent/``, ``runtime/`` or ``core/`` plus the top-level files of those three
directories. A unit is *reachable* when production code outside the unit uses it,
directly or through another reachable unit.

Evidence is expressed as fully-qualified dotted references. Every file yields the
references it really uses: imported module paths, names bound by an import and then
loaded, attribute chains on imported modules, dotted-path strings and
``module:attr`` strings. A reference resolves to a unit through the module it names;
a name imported from a hub (``__init__.py``) is followed through the hub's re-export
bindings (``from .x import Y``, ``X = Y`` aliases, lazy ``{"Name": ("module", "attr")}``
tables) and, when the hub does not bind the name, through the exporters inside the
hub's own subtree. A bare identifier that merely equals an exported name never counts.

Facade rule: in a hub imports, aliases and lazy tables are re-exports, not uses; only
real uses (calls, attribute access) count. ``api/`` and the package root
``__init__.py`` are the public surface, so everything they export counts. The server
tree is production by definition, so all of its files count like ordinary modules.
``__main__.py`` files, ``[project.scripts]`` entries and every file outside the scoped
directories are roots. Tests are never evidence.
"""

from __future__ import annotations

import ast
import re
import warnings
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

SCOPE_TOP: Final[tuple[str, ...]] = ("agent", "runtime", "core")
PUBLIC_SURFACE: Final[str] = "api"

_DOTTED: Final = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")


class Role(Enum):
    """How a file's imports are weighed as evidence."""

    MODULE = "module"  # ordinary file: imports, strings and uses all count
    HUB = "hub"  # facade __init__: only real uses count; re-exports become bindings
    SURFACE = "surface"  # public-surface __init__: counts like a module and exposes bindings


@dataclass(frozen=True)
class FileFacts:
    """Static evidence extracted from one Python file."""

    targets: frozenset[str]
    bindings: Mapping[str, str]
    exports: frozenset[str]
    lines: int


@dataclass(frozen=True)
class Unit:
    key: str
    lines: int


@dataclass(frozen=True)
class Report:
    units: dict[str, Unit]
    dead: tuple[Unit, ...]
    server_only: tuple[Unit, ...]
    files_scanned: int


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


@dataclass(frozen=True)
class _Scan:
    """The nodes that carry evidence, collected in one pass; ``loads`` keeps parent-before-child order."""

    imports: tuple[ast.Import | ast.ImportFrom, ...]
    loads: tuple[ast.Name | ast.Attribute, ...]
    strings: tuple[str, ...]
    dicts: tuple[ast.Dict, ...]


def _scan(tree: ast.Module, root: str, *, want_dicts: bool) -> _Scan:
    imports: list[ast.Import | ast.ImportFrom] = []
    loads: list[ast.Name | ast.Attribute] = []
    strings: list[str] = []
    dicts: list[ast.Dict] = []
    prefix = f"{root}."
    for node in ast.walk(tree):
        if isinstance(node, ast.Name | ast.Attribute):
            if isinstance(node.ctx, ast.Load):
                loads.append(node)
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, str) and node.value.startswith(prefix):
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


def _string_module(value: str, package: str, root: str) -> str:
    """Absolute dotted module named by an import-path string, or ``""``."""
    if value.startswith("."):
        stripped = value.lstrip(".")
        return _resolve_relative(len(value) - len(stripped), stripped or None, package)
    return value if value.startswith(f"{root}.") and _DOTTED.match(value) else ""


def _string_targets(strings: Iterable[str]) -> set[str]:
    """``root.pkg.mod`` and ``root.pkg.mod:attr`` strings (importlib / entry-point style references)."""
    found: set[str] = set()
    for value in strings:
        module, sep, attr = value.partition(":")
        if _DOTTED.match(module) and (not sep or all(part.isidentifier() for part in attr.split("."))):
            found.add(f"{module}.{attr}" if sep else module)
    return found


def _lazy_table(dicts: Iterable[ast.Dict], package: str, root: str) -> dict[str, str]:
    """Lazy hub tables ``{"Name": ("module", "attr")}`` as ``name -> dotted target``."""
    table: dict[str, str] = {}
    for node in dicts:
        for key, value in zip(node.keys, node.values, strict=True):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if not (isinstance(value, ast.Tuple | ast.List) and len(value.elts) == 2):
                continue
            parts = [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            module = _string_module(parts[0], package, root) if len(parts) == 2 else ""
            if module and parts[1].isidentifier():
                table[key.value] = f"{module}.{parts[1]}"
    return table


def _hub_bindings(tree: ast.Module, scan: _Scan, package: str, root: str) -> tuple[dict[str, str], set[int]]:
    """Names a hub re-exports and the AST node ids of its alias right-hand sides."""
    statements = list(_module_statements(tree.body))
    bound, _ = _import_bindings((n for n in statements if isinstance(n, ast.Import | ast.ImportFrom)), package)
    bindings = {**bound, **_lazy_table(scan.dicts, package, root)}
    aliased: set[int] = set()
    for node in statements:
        if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(node.value, ast.Name | ast.Attribute):
            aliased.update(id(child) for child in ast.walk(node.value))
            head, links = _chain(node.value)
            if (target := _expand(head, links, bound)) and isinstance(node, ast.Assign):
                bindings.update({t.id: target for t in node.targets if isinstance(t, ast.Name)})
    return bindings, aliased


def analyze_source(text: str, package: str, root: str, *, role: Role) -> FileFacts:
    """Extract evidence from ``text``; ``package`` is the dotted package the file lives in."""
    lines = text.count("\n") + 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return FileFacts(frozenset(), {}, frozenset(), lines)

    scan = _scan(tree, root, want_dicts=role is not Role.MODULE)
    bound, imported = _import_bindings(scan.imports, package)
    bindings: dict[str, str] = {}
    aliased: set[int] = set()
    if role is not Role.MODULE:
        bindings, aliased = _hub_bindings(tree, scan, package, root)
    targets = _used_targets(scan.loads, bound, aliased)
    if role is not Role.HUB:
        targets |= imported | _string_targets(scan.strings) | set(bindings.values())
    return FileFacts(frozenset(targets), bindings, _exports(tree), lines)


def classify(parts: tuple[str, ...]) -> tuple[str, str | None]:
    """Return ``(kind, unit_key)`` for a package-relative path; kind is ``unit`` or ``root``."""
    if parts[-1] == "__main__.py" or parts[0] not in SCOPE_TOP:
        return "root", None
    if len(parts) == 2:
        return ("root", None) if parts[1] == "__init__.py" else ("unit", f"{parts[0]}/{parts[1][:-3]}")
    if len(parts) == 3:
        return ("root", None) if parts[2] == "__init__.py" else ("unit", f"{parts[0]}/{parts[1]}/{parts[2][:-3]}")
    return "unit", f"{parts[0]}/{parts[1]}/{parts[2]}"


def _python_files(root: Path) -> Iterable[Path]:
    return (path for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts)


class _Resolver:
    """Resolves dotted references to units through module paths and hub re-exports."""

    def __init__(self, package: str) -> None:
        self.package = package
        self.module_unit: dict[str, str | None] = {}
        self.hub_bindings: dict[str, Mapping[str, str]] = {}
        self.hub_defs: dict[str, frozenset[str]] = {}
        self.exporters: dict[str, set[str]] = defaultdict(set)
        self._cache: dict[str, frozenset[str]] = {}

    def add_module(self, rel: tuple[str, ...], facts: FileFacts) -> None:
        is_init = rel[-1] == "__init__.py"
        module = ".".join([self.package, *rel[:-1], *([] if is_init else [rel[-1][:-3]])])
        self.module_unit[module] = classify(rel)[1]
        for depth in range(1, len(rel)):
            ancestor = ".".join([self.package, *rel[:depth]])
            self.module_unit.setdefault(ancestor, classify((*rel[:depth], "__init__.py"))[1])
        if is_init:
            self.hub_bindings[module] = facts.bindings
            self.hub_defs[module] = facts.exports

    def _scope_prefix(self, module: str) -> str:
        return module.removeprefix(self.package).removeprefix(".").replace(".", "/")

    def resolve(self, target: str, _seen: frozenset[str] = frozenset()) -> frozenset[str]:
        if not _seen and (cached := self._cache.get(target)) is not None:
            return cached
        parts = target.split(".")
        result: frozenset[str] = frozenset()
        for width in range(len(parts), 0, -1):
            module = ".".join(parts[:width])
            if module not in self.module_unit:
                continue
            unit, rest = self.module_unit[module], parts[width:]
            if unit:
                result = frozenset({unit})
            elif rest and (bound := self.hub_bindings.get(module, {}).get(rest[0])) and bound not in _seen:
                result = self.resolve(".".join([bound, *rest[1:]]), _seen | {target})
            elif rest and rest[0] not in self.hub_defs.get(module, ()):
                prefix = self._scope_prefix(module)
                result = frozenset(
                    u for u in self.exporters.get(rest[0], ()) if not prefix or u.startswith(f"{prefix}/")
                )
            break
        if not _seen:
            self._cache[target] = result
        return result


def _role(rel: tuple[str, ...]) -> Role:
    if rel[-1] != "__init__.py":
        return Role.MODULE
    return Role.SURFACE if len(rel) == 1 or rel[0] == PUBLIC_SURFACE else Role.HUB


def analyze(
    package_root: Path,
    external_roots: Sequence[Path] = (),
    entry_points: Iterable[str] = (),
) -> Report:
    """Compute dead units of ``package_root``; every file under ``external_roots`` is a consumer root."""
    package = package_root.name
    resolver = _Resolver(package)
    unit_targets: dict[str, set[str]] = defaultdict(set)
    unit_lines: dict[str, int] = defaultdict(int)
    root_targets: set[str] = set()
    external_targets: set[str] = set()
    files_scanned = 0

    for path in _python_files(package_root):
        rel = path.relative_to(package_root).parts
        facts = analyze_source(
            path.read_text(encoding="utf-8", errors="ignore"),
            ".".join([package, *rel[:-1]]),
            package,
            role=_role(rel),
        )
        files_scanned += 1
        resolver.add_module(rel, facts)
        key = classify(rel)[1]
        if key is None:
            root_targets |= facts.targets
            continue
        unit_targets[key] |= facts.targets
        unit_lines[key] += facts.lines
        for name in facts.exports:
            resolver.exporters[name].add(key)

    for root in external_roots:
        for path in _python_files(root):
            text = path.read_text(encoding="utf-8", errors="ignore")
            files_scanned += 1
            if package in text:
                external_targets |= analyze_source(text, "", package, role=Role.MODULE).targets

    for entry in entry_points:
        module, _, attr = entry.partition(":")
        root_targets.add(f"{module}.{attr}" if attr else module)

    def reach(seeds: Iterable[str]) -> set[str]:
        live: set[str] = set()
        queue: deque[str] = deque()

        def admit(units: Iterable[str], origin: str | None) -> None:
            for unit in units:
                if unit != origin and unit not in live:
                    live.add(unit)
                    queue.append(unit)

        for seed in seeds:
            admit(resolver.resolve(seed), None)
        while queue:
            current = queue.popleft()
            for target in unit_targets[current]:
                admit(resolver.resolve(target), current)
        return live

    live_all = reach(root_targets | external_targets)
    live_in_package = reach(root_targets)
    units = {key: Unit(key, unit_lines[key]) for key in sorted(unit_targets)}
    return Report(
        units=units,
        dead=tuple(unit for key, unit in units.items() if key not in live_all),
        server_only=tuple(unit for key, unit in units.items() if key in live_all and key not in live_in_package),
        files_scanned=files_scanned,
    )
