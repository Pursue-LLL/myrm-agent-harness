"""AST-augmented packer for 1M long-context full-repo refactoring.

Extracts repo-wide AST symbols, establishes cross-file dependency maps,
and packs the codebase into an optimized wide-context stream.

[INPUT]
- runtime.context.full_repo_refactor_types::RepoAstSymbol, RepoAstTopology, RepoFileNode, RepoSymbolKind
  (POS: Type definitions for native 1M long-context full-repo refactoring pipeline.)

[OUTPUT]
- FullRepoAstPacker: Extracts codebase topology and packages source files for 1M context windows.

[POS]
AST-augmented packer for 1M long-context full-repo refactoring.
"""

import ast
import hashlib
import os
import re

from myrm_agent_harness.runtime.context.full_repo_refactor_types import (
    RepoAstSymbol,
    RepoAstTopology,
    RepoFileNode,
    RepoSymbolKind,
)

DEFAULT_IGNORE_DIRS: set[str] = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
}

DEFAULT_ALLOWED_EXTENSIONS: set[str] = {
    ".py",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
}


class FullRepoAstPacker:
    """Extracts codebase topology and packages source files for 1M context windows."""

    def __init__(
        self,
        ignore_dirs: set[str] | None = None,
        allowed_extensions: set[str] | None = None,
    ) -> None:
        self._ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS
        self._allowed_extensions = (
            allowed_extensions or DEFAULT_ALLOWED_EXTENSIONS
        )

    def scan_and_analyze(self, repo_root: str) -> RepoAstTopology:
        """Scan repository files, parse AST, and build cross-file topology."""
        file_nodes: dict[str, RepoFileNode] = {}
        symbol_index: dict[str, list[str]] = {}
        cross_deps: dict[str, set[str]] = {}

        total_lines = 0
        total_tokens = 0

        for root, dirs, files in os.walk(repo_root):
            dirs[:] = [d for d in dirs if d not in self._ignore_dirs]
            for file in sorted(files):
                ext = os.path.splitext(file)[1].lower()
                if ext not in self._allowed_extensions:
                    continue

                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, repo_root).replace(
                    "\\", "/"
                )

                try:
                    with open(abs_path, encoding="utf-8") as f:
                        content = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                node = self._analyze_file(rel_path, content, ext)
                file_nodes[rel_path] = node
                total_lines += node.lines_count
                total_tokens += node.estimated_tokens

                for sym in node.symbols:
                    if sym.name not in symbol_index:
                        symbol_index[sym.name] = []
                    symbol_index[sym.name].append(rel_path)

        # Build cross-file dependencies based on imports and symbol occurrences
        for rel_path, node in file_nodes.items():
            deps: set[str] = set()
            for imp in node.imports:
                imp_clean = imp.replace(".", "/")
                for candidate in file_nodes:
                    cand_base = os.path.splitext(candidate)[0]
                    if (
                        cand_base.endswith(imp_clean) or imp_clean in cand_base
                    ) and candidate != rel_path:
                        deps.add(candidate)
            cross_deps[rel_path] = deps

        return RepoAstTopology(
            file_nodes=file_nodes,
            cross_file_dependencies=cross_deps,
            symbol_index=symbol_index,
            total_files=len(file_nodes),
            total_lines=total_lines,
            estimated_total_tokens=total_tokens,
        )

    def generate_topology_outline(self, topology: RepoAstTopology) -> str:
        """Render a concise markdown AST topology outline for prompt header."""
        lines: list[str] = [
            "# REPOSITORY AST TOPOLOGY & ARCHITECTURE SKELETON",
            f"- Total Files: {topology.total_files}",
            f"- Total Lines: {topology.total_lines}",
            f"- Estimated Tokens: {topology.estimated_total_tokens}",
            "",
            "## Module Hierarchy & Top-Level Symbols",
        ]

        for path, node in sorted(topology.file_nodes.items()):
            lines.append(
                f"- **`{path}`** ({node.lines_count} lines, ~{node.estimated_tokens} tokens):"
            )
            if node.symbols:
                sym_strs: list[str] = []
                for s in node.symbols[:8]:
                    sig = f"({s.signature})" if s.signature else ""
                    sym_strs.append(f"`{s.name}{sig}` [{s.kind.value}]")
                if len(node.symbols) > 8:
                    sym_strs.append(f"... (+{len(node.symbols) - 8} more)")
                lines.append(f"  - Symbols: {', '.join(sym_strs)}")

            deps = topology.cross_file_dependencies.get(path, set())
            if deps:
                sorted_deps = sorted(list(deps))[:5]
                lines.append(
                    f"  - Depends On: {', '.join([f'`{d}`' for d in sorted_deps])}"
                )

        return "\n".join(lines)

    def _analyze_file(
        self, rel_path: str, content: str, ext: str
    ) -> RepoFileNode:
        """Analyze a single file for lines, tokens, hash, and AST symbols."""
        lines = content.splitlines()
        lines_count = len(lines)
        tokens_est = max(1, len(content) // 4)
        c_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        symbols: list[RepoAstSymbol] = []
        imports: list[str] = []

        if ext == ".py":
            symbols, imports = self._parse_python_ast(content)
        elif ext in {".ts", ".js", ".tsx", ".jsx"}:
            symbols, imports = self._parse_js_ts_symbols(content)

        return RepoFileNode(
            path=rel_path,
            language=ext.lstrip("."),
            symbols=symbols,
            imports=imports,
            lines_count=lines_count,
            estimated_tokens=tokens_est,
            content_hash=c_hash,
        )

    def _parse_python_ast(
        self, content: str
    ) -> tuple[list[RepoAstSymbol], list[str]]:
        """Parse Python AST for top-level classes, functions, and imports."""
        symbols: list[RepoAstSymbol] = []
        imports: list[str] = []

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return symbols, imports

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node) or ""
                doc_summary = doc.splitlines()[0] if doc else ""
                end_lineno = getattr(node, "end_lineno", node.lineno)
                symbols.append(
                    RepoAstSymbol(
                        name=node.name,
                        kind=RepoSymbolKind.CLASS,
                        line_number=node.lineno,
                        end_line=end_lineno,
                        signature="",
                        docstring_summary=doc_summary,
                    )
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node) or ""
                doc_summary = doc.splitlines()[0] if doc else ""
                end_lineno = getattr(node, "end_lineno", node.lineno)
                args_list = [a.arg for a in node.args.args]
                sig = ", ".join(args_list)
                symbols.append(
                    RepoAstSymbol(
                        name=node.name,
                        kind=RepoSymbolKind.FUNCTION,
                        line_number=node.lineno,
                        end_line=end_lineno,
                        signature=sig,
                        docstring_summary=doc_summary,
                    )
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        return symbols, imports

    def _parse_js_ts_symbols(
        self, content: str
    ) -> tuple[list[RepoAstSymbol], list[str]]:
        """Lightweight regex extraction for JS/TS classes, functions, and imports."""
        symbols: list[RepoAstSymbol] = []
        imports: list[str] = []

        for lineno, line in enumerate(content.splitlines(), start=1):
            line_str = line.strip()
            # Class match
            m_class = re.match(
                r"^(?:export\s+)?(?:default\s+)?class\s+([A-Za-z0-9_$]+)",
                line_str,
            )
            if m_class:
                symbols.append(
                    RepoAstSymbol(
                        name=m_class.group(1),
                        kind=RepoSymbolKind.CLASS,
                        line_number=lineno,
                        end_line=lineno,
                    )
                )
                continue

            # Function match
            m_func = re.match(
                r"^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\((.*?)\)",
                line_str,
            )
            if m_func:
                symbols.append(
                    RepoAstSymbol(
                        name=m_func.group(1),
                        kind=RepoSymbolKind.FUNCTION,
                        line_number=lineno,
                        end_line=lineno,
                        signature=m_func.group(2),
                    )
                )
                continue

            # Import match
            m_imp = re.match(r'^import\s+.*?from\s+[\'"](.*?)[\'"]', line_str)
            if m_imp:
                imports.append(m_imp.group(1))

        return symbols, imports
