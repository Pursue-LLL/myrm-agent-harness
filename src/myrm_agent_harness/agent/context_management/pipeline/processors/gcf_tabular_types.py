from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GcfColumnarTable:
    """Columnar representation (Grid-Column Format) of tabular records."""

    cols: list[str]
    rows: list[list[object]]

    def to_dict(self) -> dict[str, object]:
        """Convert to standard GCF JSON dictionary."""
        return {
            "_cols": list(self.cols),
            "_rows": [list(r) for r in self.rows],
        }

    def to_json(self, indent: int | None = None) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


@dataclass(frozen=True, slots=True)
class GcfCompressionGuardConfig:
    """Config and defensive thresholds for GCF columnar compression."""

    min_rows: int = 3
    max_heterogeneity_rate: float = 0.30
    flatten_nested_dot_paths: bool = True
    min_savings_chars: int = 30


@dataclass(frozen=True, slots=True)
class GcfCompressionResult:
    """Diagnostic outcome of GCF compression execution."""

    is_compressed: bool
    original_text: str
    compressed_text: str
    cols_count: int = 0
    rows_count: int = 0
    original_chars: int = 0
    compressed_chars: int = 0
    compression_ratio: float = 0.0
    saved_chars: int = 0
    bypass_reason: str | None = None
    table: GcfColumnarTable | None = None
    metadata: dict[str, str] = field(default_factory=dict)
