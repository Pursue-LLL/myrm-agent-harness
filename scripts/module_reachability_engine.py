"""Static engine behind the module-reachability gate.

A *unit* is a direct child (file or sub-package) of a top-level directory of the package, plus the
top-level files of that directory. The files of ``root_dirs`` (default: the public surface ``api/``)
are not units but consumers by definition. A unit is *reachable* when production code outside the
unit uses it, directly or through another reachable unit.

Per-file evidence (dotted references, hub re-export bindings, the facade rule) comes from
``module_reachability_facts``. A reference resolves to a unit through the module it names; a name
imported from a hub (``__init__.py``) is followed through the hub's re-export bindings and, when the
hub does not bind the name, through the exporters inside the hub's own subtree.

Roots: package-root modules, the files of ``root_dirs``, ``__main__.py`` files and
``[project.scripts]`` entries. A downstream tree (the server) is a ``Consumer``: it is analysed with
the same engine, and only its roots and the units reachable from them count as consumers, so a dead
downstream unit cannot keep an upstream unit alive. Tests are never evidence.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.module_reachability_facts import FileFacts, Role, analyze_source

PUBLIC_SURFACE: Final[str] = "api"


@dataclass(frozen=True)
class Unit:
    key: str
    lines: int


@dataclass(frozen=True)
class Consumer:
    """A downstream tree whose live code is evidence for the analysed package."""

    root: Path
    root_dirs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Report:
    units: dict[str, Unit]
    dead: tuple[Unit, ...]
    server_only: tuple[Unit, ...]
    files_scanned: int


def classify(parts: tuple[str, ...], root_dirs: Sequence[str] = (PUBLIC_SURFACE,)) -> tuple[str, str | None]:
    """Return ``(kind, unit_key)`` for a package-relative path; kind is ``unit`` or ``root``."""
    if parts[-1] == "__main__.py" or len(parts) == 1 or parts[0] in root_dirs:
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

    def __init__(self, package: str, root_dirs: Sequence[str]) -> None:
        self.package = package
        self.root_dirs = root_dirs
        self.module_unit: dict[str, str | None] = {}
        self.hub_bindings: dict[str, Mapping[str, str]] = {}
        self.hub_defs: dict[str, frozenset[str]] = {}
        self.exporters: dict[str, set[str]] = defaultdict(set)
        self._cache: dict[str, frozenset[str]] = {}

    def add_module(self, rel: tuple[str, ...], facts: FileFacts) -> None:
        is_init = rel[-1] == "__init__.py"
        module = ".".join([self.package, *rel[:-1], *([] if is_init else [rel[-1][:-3]])])
        self.module_unit[module] = classify(rel, self.root_dirs)[1]
        for depth in range(1, len(rel)):
            ancestor = ".".join([self.package, *rel[:depth]])
            self.module_unit.setdefault(ancestor, classify((*rel[:depth], "__init__.py"), self.root_dirs)[1])
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


@dataclass
class _Graph:
    """Units, the references each makes and the roots of one package tree."""

    resolver: _Resolver
    unit_targets: dict[str, set[str]]
    unit_lines: dict[str, int]
    root_targets: set[str]
    files: int

    def reach(self, seeds: Iterable[str]) -> set[str]:
        live: set[str] = set()
        queue: deque[str] = deque()

        def admit(units: Iterable[str], origin: str | None) -> None:
            for unit in units:
                if unit != origin and unit not in live:
                    live.add(unit)
                    queue.append(unit)

        for seed in seeds:
            admit(self.resolver.resolve(seed), None)
        while queue:
            current = queue.popleft()
            for target in self.unit_targets[current]:
                admit(self.resolver.resolve(target), current)
        return live

    def evidence_for(self, package: str) -> set[str]:
        """References into ``package`` made by the roots and by every unit reachable from them."""
        live = self.reach(self.root_targets)
        targets = set(self.root_targets).union(*(self.unit_targets[unit] for unit in live))
        return {t for t in targets if t == package or t.startswith(f"{package}.")}


def _build(tree_root: Path, root_dirs: Sequence[str], foreign: Sequence[str] = ()) -> _Graph:
    """Index ``tree_root``; ``foreign`` are other packages whose references the tree makes.

    A name a hub re-exports from a foreign package cannot be followed past the tree boundary, so
    such a binding counts as a reference.
    """
    package = tree_root.name
    roots = (package, *foreign)
    foreign_prefixes = tuple(f"{name}." for name in foreign)
    graph = _Graph(_Resolver(package, root_dirs), defaultdict(set), defaultdict(int), set(), 0)
    for path in _python_files(tree_root):
        rel = path.relative_to(tree_root).parts
        facts = analyze_source(
            path.read_text(encoding="utf-8", errors="ignore"),
            ".".join([package, *rel[:-1]]),
            roots,
            role=_role(rel),
        )
        graph.files += 1
        graph.resolver.add_module(rel, facts)
        targets = facts.targets | {b for b in facts.bindings.values() if b.startswith(foreign_prefixes)}
        key = classify(rel, root_dirs)[1]
        if key is None:
            graph.root_targets |= targets
            continue
        graph.unit_targets[key] |= targets
        graph.unit_lines[key] += facts.lines
        for name in facts.exports:
            graph.resolver.exporters[name].add(key)
    return graph


def _entry_targets(entry_points: Iterable[str]) -> set[str]:
    parsed = (entry.partition(":") for entry in entry_points)
    return {f"{module}.{attr}" if attr else module for module, _, attr in parsed}


def analyze(
    package_root: Path,
    consumers: Sequence[Consumer] = (),
    entry_points: Iterable[str] = (),
    *,
    root_dirs: Sequence[str] = (PUBLIC_SURFACE,),
) -> Report:
    """Compute dead units of ``package_root``."""
    package = package_root.name
    graph = _build(package_root, root_dirs)
    files_scanned = graph.files
    consumed: set[str] = set()
    for consumer in consumers:
        tree = _build(consumer.root, consumer.root_dirs, (package,))
        files_scanned += tree.files
        consumed |= tree.evidence_for(package)

    seeds = graph.root_targets | _entry_targets(entry_points)
    live_all = graph.reach(seeds | consumed)
    live_in_package = graph.reach(seeds)
    units = {key: Unit(key, graph.unit_lines[key]) for key in sorted(graph.unit_targets)}
    return Report(
        units=units,
        dead=tuple(unit for key, unit in units.items() if key not in live_all),
        server_only=tuple(unit for key, unit in units.items() if key in live_all and key not in live_in_package),
        files_scanned=files_scanned,
    )
