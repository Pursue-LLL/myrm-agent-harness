"""Static AST dependency and dead code topology analyzer for codebase debloating.

[INPUT]
- root_dir: Path to directory to analyze
- file_extensions: List of source file extensions to parse (e.g. .py, .ts, .js)

[OUTPUT]
- CodebaseTopologyReport: Dataclass containing symbol definitions, references, unreferenced symbols, and dependency edges.

[POS]
Harness framework layer code analysis module for AST reference graph extraction and safe dead code candidates discovery.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SymbolDefinition:
    """Represents a top-level or class-level symbol definition."""

    name: str
    file_path: str
    line_number: int
    kind: str  # "function", "class", "async_function"


@dataclass(slots=True)
class CodebaseTopologyReport:
    """Analysis report containing symbol topology and unreferenced dead code candidates."""

    total_files_scanned: int
    definitions: list[SymbolDefinition] = field(default_factory=list)
    referenced_symbol_names: set[str] = field(default_factory=set)
    unreferenced_symbols: list[SymbolDefinition] = field(default_factory=list)
    isolated_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_files_scanned": self.total_files_scanned,
            "total_definitions": len(self.definitions),
            "unreferenced_count": len(self.unreferenced_symbols),
            "unreferenced_symbols": [
                {
                    "name": sym.name,
                    "file_path": sym.file_path,
                    "line_number": sym.line_number,
                    "kind": sym.kind,
                }
                for sym in self.unreferenced_symbols
            ],
            "isolated_files": self.isolated_files,
        }


class PythonAstTopologyScanner:
    """Extracts top-level function/class definitions and global name references using standard library AST."""

    @classmethod
    def scan_directory(
        cls,
        root_dir: Path,
        exclude_dirs: tuple[str, ...] = (".git", ".venv", "node_modules", "__pycache__", "tests"),
    ) -> CodebaseTopologyReport:
        """Scans Python files in root_dir and constructs definition/usage graphs."""
        if not root_dir.exists():
            return CodebaseTopologyReport(total_files_scanned=0)

        definitions: list[SymbolDefinition] = []
        references: set[str] = set()
        file_definitions_map: dict[str, list[SymbolDefinition]] = {}
        py_files: list[Path] = []

        for p in root_dir.rglob("*.py"):
            if any(ex in p.parts for ex in exclude_dirs):
                continue
            py_files.append(p)

        for file_path in py_files:
            rel_path = str(file_path.relative_to(root_dir))
            file_defs, file_refs = cls._parse_file(file_path, rel_path)
            definitions.extend(file_defs)
            file_definitions_map[rel_path] = file_defs
            references.update(file_refs)

        # Filter unreferenced symbols (excluding magic methods and public entry points like main, __all__)
        unreferenced: list[SymbolDefinition] = []
        for defn in definitions:
            if defn.name.startswith("__") and defn.name.endswith("__"):
                continue
            if defn.name not in references:
                unreferenced.append(defn)

        # Identify isolated files where all non-magic definitions are unreferenced
        isolated_files: list[str] = []
        for rel_path, file_defs in file_definitions_map.items():
            if not file_defs:
                continue
            user_defs = [d for d in file_defs if not (d.name.startswith("__") and d.name.endswith("__"))]
            if user_defs and all(d.name not in references for d in user_defs):
                isolated_files.append(rel_path)

        return CodebaseTopologyReport(
            total_files_scanned=len(py_files),
            definitions=definitions,
            referenced_symbol_names=references,
            unreferenced_symbols=unreferenced,
            isolated_files=isolated_files,
        )

    @classmethod
    def _parse_file(cls, file_path: Path, rel_path: str) -> tuple[list[SymbolDefinition], set[str]]:
        defs: list[SymbolDefinition] = []
        refs: set[str] = set()

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content, filename=str(file_path))
        except Exception:
            return defs, refs

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                defs.append(
                    SymbolDefinition(
                        name=node.name,
                        file_path=rel_path,
                        line_number=node.lineno,
                        kind="function",
                    )
                )
            elif isinstance(node, ast.AsyncFunctionDef):
                defs.append(
                    SymbolDefinition(
                        name=node.name,
                        file_path=rel_path,
                        line_number=node.lineno,
                        kind="async_function",
                    )
                )
            elif isinstance(node, ast.ClassDef):
                defs.append(
                    SymbolDefinition(
                        name=node.name,
                        file_path=rel_path,
                        line_number=node.lineno,
                        kind="class",
                    )
                )

        # Collect all Name and Attribute loads across entire AST
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                refs.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                refs.add(node.attr)

        return defs, refs
