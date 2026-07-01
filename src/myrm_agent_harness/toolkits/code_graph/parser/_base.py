"""Language parser protocol and shared types for AST-based code extraction.

[INPUT]
- str (POS: source code text)
- str (POS: file path for context)

[OUTPUT]
- LanguageParser: Protocol defining the parse contract
- ParseResult: extracted nodes and edges from a single file
- SUPPORTED_LANGUAGES: mapping of file extensions to language identifiers

[POS]
Defines the contract that all per-language Tree-sitter extractors implement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.code_graph.store import GraphEdge, GraphNode


@dataclass(slots=True)
class ParseResult:
    """Extraction result from parsing a single source file."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    language: str = ""
    errors: list[str] = field(default_factory=list)


@runtime_checkable
class LanguageParser(Protocol):
    """Contract for per-language AST extractors."""

    @property
    def language_id(self) -> str:
        """Unique identifier for this language (e.g., 'python', 'javascript')."""
        ...

    @property
    def file_extensions(self) -> frozenset[str]:
        """File extensions this parser handles (e.g., {'.py'})."""
        ...

    def parse(self, source: str, file_path: str) -> ParseResult:
        """Parse source code and extract nodes + edges.

        Args:
            source: The source code text to parse.
            file_path: Relative file path (used for qualified names).

        Returns:
            ParseResult with extracted nodes and edges.
        """
        ...


SUPPORTED_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
}
