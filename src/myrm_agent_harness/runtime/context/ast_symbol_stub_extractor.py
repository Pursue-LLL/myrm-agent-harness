"""AST symbol stub extractor for lightweight code signature harvesting.

Extracts top-level class and function signatures, decorators, and docstring
summaries from source code, constructing persistent lightweight symbol stubs
that remain resident in active context even when source bodies are paged out.

[INPUT]
- runtime.context.virtual_paged_code_types::CodeSymbolStub (POS: Virtual paged code context tiering and swap
  engine types.)

[OUTPUT]
- AstSymbolStubExtractor: Extracts compact symbol signatures and doc summaries from source code.

[POS]
AST symbol stub extractor for lightweight code signature harvesting.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Sequence

from .virtual_paged_code_types import CodeSymbolStub


class AstSymbolStubExtractor:
    """Extracts compact symbol signatures and doc summaries from source code."""

    def extract_stubs(self, file_path: str, code_content: str) -> tuple[CodeSymbolStub, ...]:
        """Parses source code into a tuple of CodeSymbolStub objects."""
        if not code_content.strip():
            return ()

        # Prefer native Python AST parser for .py files
        if file_path.endswith(".py"):
            try:
                return self._extract_python_ast(code_content)
            except Exception:
                # Fallback to regex parser on syntax errors or partial snippets
                return self._extract_regex_stubs(code_content)

        return self._extract_regex_stubs(code_content)

    def format_stubs_manifest(
        self,
        file_path: str,
        stubs: Sequence[CodeSymbolStub],
    ) -> str:
        """Formats a compact single-line or multi-line stub header for resident context."""
        if not stubs:
            return f"# Stub: {file_path} (Archived, no top-level symbols)"

        symbol_descs = [f"{s.kind.capitalize()} {s.signature}" for s in stubs]
        symbols_str = ", ".join(symbol_descs)
        return f"# Stub: {file_path} (Archived) [{symbols_str}]"

    def _extract_python_ast(self, code: str) -> tuple[CodeSymbolStub, ...]:
        """Uses python ast module to extract class and function definitions."""
        tree = ast.parse(code)
        stubs: list[CodeSymbolStub] = []

        lines = code.splitlines()

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sig = self._format_ast_function_signature(node, lines)
                doc = ast.get_docstring(node) or ""
                doc_first_line = doc.strip().splitlines()[0] if doc.strip() else ""
                end_lineno = getattr(node, "end_lineno", node.lineno)
                stubs.append(
                    CodeSymbolStub(
                        symbol_name=node.name,
                        kind="function",
                        signature=sig,
                        doc_summary=doc_first_line[:80],
                        line_start=node.lineno,
                        line_end=end_lineno,
                    )
                )
            elif isinstance(node, ast.ClassDef):
                sig = f"class {node.name}"
                if node.bases:
                    bases_str = ", ".join(ast.unparse(b) for b in node.bases)
                    sig = f"class {node.name}({bases_str})"
                doc = ast.get_docstring(node) or ""
                doc_first_line = doc.strip().splitlines()[0] if doc.strip() else ""
                end_lineno = getattr(node, "end_lineno", node.lineno)
                stubs.append(
                    CodeSymbolStub(
                        symbol_name=node.name,
                        kind="class",
                        signature=sig,
                        doc_summary=doc_first_line[:80],
                        line_start=node.lineno,
                        line_end=end_lineno,
                    )
                )

        return tuple(stubs)

    def _format_ast_function_signature(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        lines: list[str],
    ) -> str:
        """Constructs concise function signature string."""
        prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
        line_idx = node.lineno - 1
        if 0 <= line_idx < len(lines):
            raw_line = lines[line_idx].strip()
            # Capture def statement up to colon
            match = re.search(r"^(async\s+def|def)\s+[\w_]+\([^)]*\)(\s*->\s*[^:]+)?", raw_line)
            if match:
                return match.group(0).strip()
        return f"{prefix}{node.name}(...)"

    def _extract_regex_stubs(self, code: str) -> tuple[CodeSymbolStub, ...]:
        """Fallback regex extractor for non-Python or unparseable source files."""
        stubs: list[CodeSymbolStub] = []
        for idx, line in enumerate(code.splitlines(), start=1):
            line_str = line.strip()
            # Match class definitions
            class_match = re.match(r"^(class|export class|public class)\s+([\w_]+)", line_str)
            if class_match:
                name = class_match.group(2)
                stubs.append(
                    CodeSymbolStub(
                        symbol_name=name,
                        kind="class",
                        signature=line_str.rstrip("{:"),
                        doc_summary="",
                        line_start=idx,
                        line_end=idx,
                    )
                )
                continue

            # Match function/method definitions
            fn_match = re.match(
                r"^(async\s+def|def|function|export function|public async|async)\s+([\w_]+)\s*\(",
                line_str,
            )
            if fn_match:
                name = fn_match.group(2)
                stubs.append(
                    CodeSymbolStub(
                        symbol_name=name,
                        kind="function",
                        signature=line_str.rstrip("{:"),
                        doc_summary="",
                        line_start=idx,
                        line_end=idx,
                    )
                )

        return tuple(stubs)
