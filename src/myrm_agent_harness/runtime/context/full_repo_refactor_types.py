"""Type definitions for native 1M long-context full-repo refactoring pipeline.

Provides structured models for repo AST topology, attention anchors,
cross-file atomic diffs, and verification results.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class RepoSymbolKind(StrEnum):
    """Kinds of top-level code symbols extracted for AST topology."""

    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    CONSTANT = "constant"
    INTERFACE = "interface"
    ENUM = "enum"
    MODULE = "module"


@dataclass(frozen=True)
class RepoAstSymbol:
    """A top-level symbol extracted from source AST."""

    name: str
    kind: RepoSymbolKind
    line_number: int
    end_line: int
    signature: str = ""
    docstring_summary: str = ""


@dataclass(frozen=True)
class RepoFileNode:
    """Metadata and extracted AST symbols for a single file in the repository."""

    path: str
    language: str
    symbols: list[RepoAstSymbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    lines_count: int = 0
    estimated_tokens: int = 0
    content_hash: str = ""


@dataclass(frozen=True)
class RepoAstTopology:
    """Global AST topology skeleton of the entire codebase."""

    file_nodes: dict[str, RepoFileNode] = field(default_factory=dict)
    cross_file_dependencies: dict[str, set[str]] = field(default_factory=dict)
    symbol_index: dict[str, list[str]] = field(default_factory=dict)
    total_files: int = 0
    total_lines: int = 0
    estimated_total_tokens: int = 0


@dataclass(frozen=True)
class SemanticAnchor:
    """Lost-in-the-middle attention anchor injected across the 1M context."""

    anchor_id: str
    symbol_name: str
    file_path: str
    definition_line: int
    fan_in_references: list[str] = field(default_factory=list)
    prompt_hint: str = ""


@dataclass(frozen=True)
class PackedRepoContext:
    """Complete 1M-token wide-context serialization for global refactoring."""

    header_topology_outline: str
    semantic_anchors: list[SemanticAnchor]
    structured_files: dict[str, str]
    full_packed_prompt: str
    total_estimated_tokens: int
    file_hashes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FileAtomicDiff:
    """Atomic replacement specification for a single file."""

    file_path: str
    expected_base_hash: str | None = None
    symbol_anchor_name: str | None = None
    target_snippet: str = ""
    replacement_snippet: str = ""
    line_hint: int | None = None


@dataclass(frozen=True)
class RefactorPlanBundle:
    """Bundle of coordinated cross-file atomic diffs for a refactor turn."""

    plan_id: str
    goal_description: str
    diffs: list[FileAtomicDiff] = field(default_factory=list)

    @property
    def affected_files(self) -> list[str]:
        """Return list of distinct affected file paths."""
        seen: set[str] = set()
        ordered: list[str] = []
        for diff in self.diffs:
            if diff.file_path not in seen:
                seen.add(diff.file_path)
                ordered.append(diff.file_path)
        return ordered


@dataclass(frozen=True)
class RefactorApplyResult:
    """Result of attempting an atomic cross-file refactor transaction."""

    success: bool
    applied_files: list[str] = field(default_factory=list)
    rolled_back_files: list[str] = field(default_factory=list)
    error_message: str | None = None
    updated_file_hashes: dict[str, str] = field(default_factory=dict)
