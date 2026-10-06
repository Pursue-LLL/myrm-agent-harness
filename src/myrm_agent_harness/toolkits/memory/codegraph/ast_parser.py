# [INPUT] Source code strings or file paths to extract AST symbols and call dependencies.
# [OUTPUT] Extracted CodeSymbol entities and DependencyEdge relations for the module.
# [POS] myrm_agent_harness.toolkits.memory.codegraph.ast_parser

"""AST-based code symbol and topology dependency extractor."""

import ast
from pathlib import Path

from myrm_agent_harness.toolkits.memory.codegraph.types import (
    CodeSymbol,
    DependencyEdge,
    EdgeKind,
    SymbolKind,
)


class AstTopologyExtractor:
    """Extracts semantic symbols and intra-file call relations from Python AST."""

    def __init__(self) -> None:
        pass

    def extract_from_source(
        self, source_code: str, file_path: str
    ) -> tuple[list[CodeSymbol], list[DependencyEdge]]:
        """Parse source code string and extract declared symbols and call edges."""
        symbols: list[CodeSymbol] = []
        edges: list[DependencyEdge] = []

        try:
            tree = ast.parse(source_code, filename=file_path)
        except (SyntaxError, UnicodeDecodeError):
            # Graceful degradation on unparseable / syntax-invalid files
            return symbols, edges

        module_visitor = _ModuleTopologyVisitor(file_path=file_path)
        module_visitor.visit(tree)

        return module_visitor.symbols, module_visitor.edges

    def extract_from_file(
        self, file_path: Path | str
    ) -> tuple[list[CodeSymbol], list[DependencyEdge]]:
        """Read source file from path and extract declared symbols and call edges."""
        path_obj = Path(file_path)
        if not path_obj.exists() or not path_obj.is_file():
            return [], []
        try:
            source_code = path_obj.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return [], []
        return self.extract_from_source(source_code, str(path_obj))


class _ModuleTopologyVisitor(ast.NodeVisitor):
    """Internal AST visitor traversing top-level and class-level structures."""

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self.file_path = file_path
        self.symbols: list[CodeSymbol] = []
        self.edges: list[DependencyEdge] = []
        self._current_scope: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        symbol_id = f"{self.file_path}::{node.name}"
        bases: list[str] = []
        for base_expr in node.bases:
            if isinstance(base_expr, ast.Name):
                bases.append(base_expr.id)
                self.edges.append(
                    DependencyEdge(
                        source_id=symbol_id,
                        target_id=base_expr.id,
                        edge_kind=EdgeKind.INHERITS,
                    )
                )
            elif isinstance(base_expr, ast.Attribute):
                bases.append(base_expr.attr)

        docstring = ast.get_docstring(node) or ""
        self.symbols.append(
            CodeSymbol(
                symbol_id=symbol_id,
                name=node.name,
                kind=SymbolKind.CLASS,
                file_path=self.file_path,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                docstring=docstring,
                parameters=[],
                return_type="",
                base_classes=bases,
            )
        )

        self._current_scope.append(node.name)
        self.generic_visit(node)
        self._current_scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function_node(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function_node(node)

    def _handle_function_node(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        is_method = len(self._current_scope) > 0
        kind = SymbolKind.METHOD if is_method else SymbolKind.FUNCTION

        if is_method:
            parent_class = self._current_scope[-1]
            symbol_id = f"{self.file_path}::{parent_class}.{node.name}"
        else:
            symbol_id = f"{self.file_path}::{node.name}"

        params = [arg.arg for arg in node.args.args if arg.arg != "self"]
        docstring = ast.get_docstring(node) or ""
        return_type = ""
        if node.returns and isinstance(node.returns, ast.Name):
            return_type = node.returns.id

        self.symbols.append(
            CodeSymbol(
                symbol_id=symbol_id,
                name=node.name,
                kind=kind,
                file_path=self.file_path,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                docstring=docstring,
                parameters=params,
                return_type=return_type,
                base_classes=[],
            )
        )

        self._current_scope.append(node.name)
        # Scan internal calls within function body
        call_scanner = _CallExprScanner(caller_id=symbol_id)
        for child in node.body:
            call_scanner.visit(child)
        self.edges.extend(call_scanner.call_edges)

        self.generic_visit(node)
        self._current_scope.pop()


class _CallExprScanner(ast.NodeVisitor):
    """Scans Call AST nodes inside a function/method body."""

    def __init__(self, caller_id: str) -> None:
        super().__init__()
        self.caller_id = caller_id
        self.call_edges: list[DependencyEdge] = []

    def visit_Call(self, node: ast.Call) -> None:
        callee_name = ""
        if isinstance(node.func, ast.Name):
            callee_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            callee_name = node.func.attr

        if callee_name:
            self.call_edges.append(
                DependencyEdge(
                    source_id=self.caller_id,
                    target_id=callee_name,
                    edge_kind=EdgeKind.CALLS,
                )
            )
        self.generic_visit(node)
