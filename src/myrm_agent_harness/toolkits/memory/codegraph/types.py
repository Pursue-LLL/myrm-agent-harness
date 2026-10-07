"""Domain models and type definitions for CodeGraph memory assets and impact analysis.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SymbolKind: Categorization of code symbols discovered in the workspace.
- EdgeKind: Categorization of structural dependencies between symbols.
- ImpactRiskLevel: Assessment of risk level when modifying a specific symbol.
- CodeSymbol: Represents an atomic semantic code symbol in the workspace.
- DependencyEdge: Directed dependency relation from one symbol/file to another.
- ImpactAnalysisReport: Pre-modification impact analysis result evaluated by the CodeGraph engine.
- CodeGraphAsset: Persistent project-level CodeGraph memory asset snapshot.

[POS]
Domain models and type definitions for CodeGraph memory assets and impact analysis.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class SymbolKind(StrEnum):
    """Categorization of code symbols discovered in the workspace."""

    FUNCTION = "FUNCTION"
    CLASS = "CLASS"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"


class EdgeKind(StrEnum):
    """Categorization of structural dependencies between symbols."""

    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPORTS = "IMPORTS"


class ImpactRiskLevel(StrEnum):
    """Assessment of risk level when modifying a specific symbol."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class CodeSymbol:
    """Represents an atomic semantic code symbol in the workspace."""

    symbol_id: str
    name: str
    kind: SymbolKind
    file_path: str
    line_start: int
    line_end: int
    docstring: str = ""
    parameters: list[str] = field(default_factory=list)
    return_type: str = ""
    base_classes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DependencyEdge:
    """Directed dependency relation from one symbol/file to another."""

    source_id: str
    target_id: str
    edge_kind: EdgeKind


@dataclass(frozen=True)
class ImpactAnalysisReport:
    """Pre-modification impact analysis result evaluated by the CodeGraph engine."""

    target_symbol_id: str
    target_symbol_name: str
    file_path: str
    blast_radius: int
    risk_level: ImpactRiskLevel
    direct_callers: list[str] = field(default_factory=list)
    indirect_callers: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    safety_recommendations: list[str] = field(default_factory=list)


@dataclass
class CodeGraphAsset:
    """Persistent project-level CodeGraph memory asset snapshot."""

    repo_id: str
    version_hash: str
    total_symbols: int
    total_edges: int
    updated_at: float
    symbols: dict[str, CodeSymbol] = field(default_factory=dict)
    edges: list[DependencyEdge] = field(default_factory=list)
