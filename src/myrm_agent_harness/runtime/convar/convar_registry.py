"""Central registry and type coercer for declared Convar definitions.

Benchmarked against Source engine Convar registration invariants:
- Enforces strict schema, default values, documentation, and bitflags at declaration.
- Coerces string representations to strongly typed primitives (str, int, float, bool).
- Validates numerical boundary constraints (min_val / max_val).
- Prevents rogue hallucinated configuration names by validating against registered definitions.

[OUTPUT]
- ConvarRegistry: Repository of authorized Convar declarations with coercion logic.

[INPUT]
- __future__

[OUTPUT]
- ConvarRegistry

[POS]
Central registry and type coercer for declared Convar definitions.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.convar.convar_types import (
    ConvarDefinition,
    ConvarFlags,
    ConvarType,
)


class ConvarRegistry:
    """Stores authoritative Convar prototypes and governs type conversion and validation."""

    def __init__(self) -> None:
        self._definitions: dict[str, ConvarDefinition] = {}

    def register(self, definition: ConvarDefinition) -> None:
        """Register a new Convar definition prototype."""
        # Validate that the default value complies with definition type and bounds
        self.coerce_value(definition, definition.default_value)
        self._definitions[definition.name] = definition

    def get_definition(self, name: str) -> ConvarDefinition | None:
        """Look up the definition schema for a given Convar name."""
        return self._definitions.get(name)

    def has(self, name: str) -> bool:
        """Check if a Convar name is officially declared in the registry."""
        return name in self._definitions

    def list_definitions(
        self, flag_filter: ConvarFlags | None = None
    ) -> list[ConvarDefinition]:
        """List registered definitions, optionally filtered by required bitflags."""
        if flag_filter is None:
            return list(self._definitions.values())
        return [
            defn
            for defn in self._definitions.values()
            if (defn.flags & flag_filter) == flag_filter
        ]

    @staticmethod
    def coerce_value(
        defn: ConvarDefinition, raw_val: str
    ) -> tuple[str, str | int | float | bool]:
        """Coerce raw text to definition type and validate boundary constraints.

        Returns:
            Tuple of (canonical_raw_str, strongly_typed_val).

        Raises:
            ValueError: If parsing fails or numerical values breach declared limits.
        """
        trimmed = raw_val.strip()

        if defn.convar_type == ConvarType.STR:
            return trimmed, trimmed

        if defn.convar_type == ConvarType.INT:
            try:
                val_int = int(trimmed)
            except ValueError as err:
                raise ValueError(
                    f"Convar '{defn.name}' expects integer, got '{trimmed}'"
                ) from err

            if defn.min_val is not None and val_int < int(defn.min_val):
                raise ValueError(
                    f"Convar '{defn.name}' value {val_int} is below minimum {int(defn.min_val)}"
                )
            if defn.max_val is not None and val_int > int(defn.max_val):
                raise ValueError(
                    f"Convar '{defn.name}' value {val_int} exceeds maximum {int(defn.max_val)}"
                )
            return str(val_int), val_int

        if defn.convar_type == ConvarType.FLOAT:
            try:
                val_float = float(trimmed)
            except ValueError as err:
                raise ValueError(
                    f"Convar '{defn.name}' expects float, got '{trimmed}'"
                ) from err

            if defn.min_val is not None and val_float < defn.min_val:
                raise ValueError(
                    f"Convar '{defn.name}' value {val_float} is below minimum {defn.min_val}"
                )
            if defn.max_val is not None and val_float > defn.max_val:
                raise ValueError(
                    f"Convar '{defn.name}' value {val_float} exceeds maximum {defn.max_val}"
                )
            return str(val_float), val_float

        if defn.convar_type == ConvarType.BOOL:
            lower = trimmed.lower()
            if lower in ("1", "true", "yes", "on"):
                return "1", True
            if lower in ("0", "false", "no", "off"):
                return "0", False
            raise ValueError(
                f"Convar '{defn.name}' expects boolean (1/0, true/false), got '{trimmed}'"
            )

        return trimmed, trimmed
