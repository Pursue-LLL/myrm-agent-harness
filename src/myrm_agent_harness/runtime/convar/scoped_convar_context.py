"""Hierarchical scoped Convar context with inheritance, dirty tracking, and cfg serialization.

Benchmarked against Source engine scoped Convars and Can Bölük's Harness Playbook:
- Forms a tree-structured scope hierarchy (Global -> Session -> Subagent).
- Reading walks up the ancestor chain; writing stores in the local scope without polluting parents.
- Enforces READ_ONLY mutation barriers and triggers change listeners on state update.
- Tracks dirty modifications for delta synchronization.
- Loads and exports standardized .cfg formatted configuration files.

[OUTPUT]
- ScopedConvarContext: Hierarchical execution scope holding local overrides and dirty state.

[INPUT]
- __future__
- re
- collections

[OUTPUT]
- ConvarChangeListener
- ScopedConvarContext

[POS]
Hierarchical scoped Convar context with inheritance, dirty tracking, and cfg serialization.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from myrm_agent_harness.runtime.convar.convar_registry import ConvarRegistry
from myrm_agent_harness.runtime.convar.convar_types import (
    ConvarFlags,
    ConvarSnapshot,
)

# Listener signature: (convar_name, old_raw, new_raw, new_typed)
ConvarChangeListener = Callable[[str, str, str, str | int | float | bool], None]


class ScopedConvarContext:
    """Manages scoped configuration variables with ancestor fallback and copy-on-write isolation."""

    def __init__(
        self,
        scope_name: str,
        registry: ConvarRegistry,
        parent: ScopedConvarContext | None = None,
    ) -> None:
        self.scope_name = scope_name
        self.registry = registry
        self.parent = parent
        self._local_values: dict[str, str] = {}
        self._dirty_keys: set[str] = set()
        self._listeners: list[ConvarChangeListener] = []

    def add_listener(self, listener: ConvarChangeListener) -> None:
        """Register a callback invoked whenever any Convar changes in this scope."""
        self._listeners.append(listener)

    def is_dirty(self, name: str) -> bool:
        """Check if a specific Convar has been modified in this local scope."""
        return name in self._dirty_keys

    def clear_dirty(self, name: str | None = None) -> None:
        """Clear dirty flags locally for a specific variable or all variables."""
        if name is not None:
            self._dirty_keys.discard(name)
        else:
            self._dirty_keys.clear()

    def get_raw(self, name: str) -> str:
        """Retrieve raw string representation, falling back to parent or registered default.

        Raises:
            KeyError: If the variable has not been declared in the Convar registry.
        """
        if name in self._local_values:
            return self._local_values[name]

        if self.parent is not None:
            return self.parent.get_raw(name)

        defn = self.registry.get_definition(name)
        if defn is None:
            raise KeyError(f"Convar '{name}' is not declared in registry")
        return defn.default_value

    def get_typed(self, name: str) -> str | int | float | bool:
        """Retrieve strongly typed primitive value coerced according to schema definition."""
        defn = self.registry.get_definition(name)
        if defn is None:
            raise KeyError(f"Convar '{name}' is not declared in registry")

        raw = self.get_raw(name)
        _, typed_val = ConvarRegistry.coerce_value(defn, raw)
        return typed_val

    def set(self, name: str, value: str | int | float | bool) -> None:
        """Assign a new value into this local scope with validation, dirty-marking, and notification.

        Raises:
            KeyError: If the variable is not registered.
            PermissionError: If the variable carries the READ_ONLY flag.
            ValueError: If the value fails type or boundary constraints.
        """
        defn = self.registry.get_definition(name)
        if defn is None:
            raise KeyError(f"Cannot set undeclared Convar '{name}'")

        if bool(defn.flags & ConvarFlags.READ_ONLY) and name in self._local_values:
            raise PermissionError(f"Convar '{name}' is marked READ_ONLY and cannot be mutated")

        old_raw = self.get_raw(name)
        raw_str, typed_val = ConvarRegistry.coerce_value(defn, str(value))

        if old_raw != raw_str:
            self._local_values[name] = raw_str
            self._dirty_keys.add(name)

            for listener in self._listeners:
                listener(name, old_raw, raw_str, typed_val)

    def snapshot(self, name: str) -> ConvarSnapshot:
        """Produce an immutable snapshot of a single Convar's state in this scope."""
        raw = self.get_raw(name)
        typed_val = self.get_typed(name)
        return ConvarSnapshot(
            name=name,
            raw_value=raw,
            typed_value=typed_val,
            is_dirty=self.is_dirty(name),
            scope_name=self.scope_name,
        )

    def fork_child(self, child_scope_name: str) -> ScopedConvarContext:
        """Spawn a child scope (e.g. for a subagent) inheriting all settings with local override isolation."""
        return ScopedConvarContext(
            scope_name=child_scope_name,
            registry=self.registry,
            parent=self,
        )

    def load_cfg(self, cfg_text: str) -> int:
        """Parse standard Source-engine .cfg lines (e.g., `cvar_name "val"` or `cvar_name val`).

        Returns:
            Number of successfully parsed and applied configuration assignments.
        """
        pattern = re.compile(r'^\s*([a-zA-Z0-9_.-]+)\s+(?:"([^"]*)"|([^\s#]+))\s*(?:#.*)?$')
        applied_count = 0

        for line in cfg_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue

            match = pattern.match(stripped)
            if not match:
                continue

            name = match.group(1)
            val = match.group(2) if match.group(2) is not None else match.group(3)

            if self.registry.has(name):
                self.set(name, val)
                applied_count += 1

        return applied_count

    def export_cfg(self, flag_filter: ConvarFlags | None = None) -> str:
        """Serialize active configuration values matching given flags to standard .cfg format."""
        definitions = self.registry.list_definitions(flag_filter)
        lines: list[str] = [
            f"# Generated Convar Configuration - Scope: {self.scope_name}",
            "# Format: <convar_name> \"<value>\"",
            "",
        ]

        for defn in sorted(definitions, key=lambda d: d.name):
            raw_val = self.get_raw(defn.name)
            lines.append(f'{defn.name} "{raw_val}"')

        return "\n".join(lines)
