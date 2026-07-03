"""Tool registry data models used by scanner, CLI, and architecture tests.

Keeping models in a dedicated module lets the scanner stay focused on AST
traversal logic and keeps the public surface of `tool_registry_engine` minimal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scripts.tool_registry_config import (
    INTERNAL_TOOL_NAMES,
    INTERNAL_TOOL_PREFIXES,
    ORPHAN_FACTORY_WHITELIST,
    PTC_RUNTIME_TOOL_NAMES,
    SCHEMA_ONLY_TOOL_NAMES,
)


@dataclass(frozen=True)
class ToolDeclaration:
    """A single tool declaration discovered by static analysis."""

    name: str
    kind: str
    file: Path
    line: int
    container: str | None = None


@dataclass
class ScanReport:
    """Aggregated results of a single registry validation run."""

    declarations: list[ToolDeclaration] = field(default_factory=list)
    registered_names: set[str] = field(default_factory=set)
    factories: dict[str, Path] = field(default_factory=dict)
    factory_call_sites: dict[str, list[Path]] = field(default_factory=dict)
    files_scanned: int = 0

    @property
    def declared_names(self) -> set[str]:
        return {d.name for d in self.declarations}

    def missing_registrations(self) -> set[str]:
        """Tools defined in code but never registered in `_TOOL_LAYERS`."""
        return {
            name
            for name in self.declared_names - self.registered_names
            if not self._is_internal(name)
        }

    def ghost_registrations(self) -> set[str]:
        """Tools registered in `_TOOL_LAYERS` but no source defines them."""
        return (
            self.registered_names
            - self.declared_names
            - INTERNAL_TOOL_NAMES
            - SCHEMA_ONLY_TOOL_NAMES
        )

    def ghost_registry_metadata_keys(self, metadata_keys: set[str]) -> set[str]:
        """Registry metadata keys (permission map, tool groups, etc.) with no tool source."""
        allowed = (
            self.declared_names
            | self.registered_names
            | INTERNAL_TOOL_NAMES
            | SCHEMA_ONLY_TOOL_NAMES
        )
        return metadata_keys - allowed

    def orphan_factories(self) -> set[str]:
        """Factory functions with zero outbound call sites."""
        return {
            factory
            for factory in self.factories
            if factory not in ORPHAN_FACTORY_WHITELIST
            and not self.factory_call_sites.get(factory)
        }

    def duplicate_declarations(self) -> dict[str, list[ToolDeclaration]]:
        """Detect identical tool names declared from multiple source files.

        Two tools sharing a name at runtime would overwrite each other in the
        registry, silently dropping one — a hard-to-debug correctness hazard.
        Renames inside a single file (declaration + middleware mutation) are
        legitimate and excluded by file-uniqueness.
        """
        by_name: dict[str, list[ToolDeclaration]] = {}
        for decl in self.declarations:
            if self._is_internal(decl.name):
                continue
            by_name.setdefault(decl.name, []).append(decl)
        return {
            name: decls
            for name, decls in by_name.items()
            if len({decl.file for decl in decls}) > 1
        }

    @staticmethod
    def _is_internal(name: str) -> bool:
        if name in INTERNAL_TOOL_NAMES:
            return True
        if name in PTC_RUNTIME_TOOL_NAMES:
            return True
        return any(name.startswith(p) for p in INTERNAL_TOOL_PREFIXES)


__all__ = ["ScanReport", "ToolDeclaration"]
