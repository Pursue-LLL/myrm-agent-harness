"""AST-based and regex-fallback code skeleton extractor for multi-tier compression.

[INPUT]
- toolkits.memory.compaction.types::CodeAbstractionLevel (POS: Type definitions and contracts for
  Token-Budget-Aware Code Memory Compaction.)

[OUTPUT]
- CodeSkeletonExtractor: Extracts structural signatures (L1) and control-flow skeletons (L2) from source
  code.

[POS]
AST-based and regex-fallback code skeleton extractor for multi-tier compression.
"""

from __future__ import annotations

import ast
import re

from .types import CodeAbstractionLevel


class CodeSkeletonExtractor:
    """Extracts structural signatures (L1) and control-flow skeletons (L2) from source code."""

    @classmethod
    def estimate_tokens(cls, text: str, ratio: float = 0.26) -> int:
        """Estimate token count for a code string using character-to-token ratio heuristic."""
        if not text:
            return 0
        return max(1, int(len(text) * ratio))

    @classmethod
    def extract_skeleton(
        cls,
        source_code: str,
        level: CodeAbstractionLevel,
        strip_private: bool = False,
        language: str = "python",
    ) -> str:
        """Extract a skeleton at the designated abstraction level."""
        if level == CodeAbstractionLevel.L3_FULL_SOURCE:
            return source_code

        clean_code = source_code.strip()
        if not clean_code:
            return ""

        if language.lower() == "python":
            try:
                if level == CodeAbstractionLevel.L1_SIGNATURES:
                    return cls._extract_python_l1(clean_code, strip_private=strip_private)
                if level == CodeAbstractionLevel.L2_CONTROL_FLOW:
                    return cls._extract_python_l2(clean_code, strip_private=strip_private)
            except SyntaxError:
                # Fallback to line-based heuristic if code snippet is partial or has syntax issues
                pass

        # Language fallback / partial snippet fallback
        if level == CodeAbstractionLevel.L1_SIGNATURES:
            return cls._extract_fallback_l1(clean_code, strip_private=strip_private)
        return cls._extract_fallback_l2(clean_code, strip_private=strip_private)

    @classmethod
    def _extract_python_l1(cls, source_code: str, strip_private: bool = False) -> str:
        """Extract Python L1 interface signatures (classes, methods, type annotations)."""
        tree = ast.parse(source_code)
        transformer = _PythonL1Transformer(strip_private=strip_private)
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        return ast.unparse(new_tree).strip()

    @classmethod
    def _extract_python_l2(cls, source_code: str, strip_private: bool = False) -> str:
        """Extract Python L2 skeleton (signatures, docstrings, and control-flow branches)."""
        tree = ast.parse(source_code)
        transformer = _PythonL2Transformer(strip_private=strip_private)
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        return ast.unparse(new_tree).strip()

    @classmethod
    def _extract_fallback_l1(cls, source_code: str, strip_private: bool = False) -> str:
        """Fallback line-based extractor for L1 signatures across languages."""
        lines = source_code.splitlines()
        extracted: list[str] = []
        sig_pattern = re.compile(
            r"^\s*(?:(?:export|async|public|private|protected|static|def|class|interface|type|fn)\s+)+",
        )

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if strip_private and (stripped.startswith("_") or "private " in line):
                continue
            if sig_pattern.match(line) or stripped.endswith(":") or stripped.endswith("{"):
                extracted.append(line.rstrip())
        return "\n".join(extracted)

    @classmethod
    def _extract_fallback_l2(cls, source_code: str, strip_private: bool = False) -> str:
        """Fallback line-based extractor for L2 control flow across languages."""
        lines = source_code.splitlines()
        extracted: list[str] = []
        cf_pattern = re.compile(
            r"^\s*(?:if|elif|else|for|while|try|except|finally|catch|raise|throw|return)\b",
        )
        sig_pattern = re.compile(
            r"^\s*(?:(?:export|async|public|private|protected|static|def|class|interface|type|fn)\s+)+",
        )

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if strip_private and (stripped.startswith("_") or "private " in line):
                continue
            if sig_pattern.match(line) or cf_pattern.match(line) or stripped.startswith(('"""', "'''")):
                extracted.append(line.rstrip())
        return "\n".join(extracted)


class _PythonL1Transformer(ast.NodeTransformer):
    """AST transformer that strips function bodies down to Ellipsis."""

    def __init__(self, strip_private: bool = False) -> None:
        self.strip_private = strip_private

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST | None:
        if self.strip_private and node.name.startswith("_"):
            return None
        self.generic_visit(node)
        if not node.body:
            node.body = [ast.Expr(value=ast.Constant(value=...))]
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST | None:
        return self._transform_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST | None:
        return self._transform_func(node)

    def _transform_func(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> ast.AST | None:
        if self.strip_private and node.name.startswith("_") and not (
            node.name.startswith("__") and node.name.endswith("__")
        ):
            return None
        # Replace body with Ellipsis
        node.body = [ast.Expr(value=ast.Constant(value=...))]
        return node


class _PythonL2Transformer(ast.NodeTransformer):
    """AST transformer that keeps docstrings, signatures, and high-level control-flow branches."""

    def __init__(self, strip_private: bool = False) -> None:
        self.strip_private = strip_private

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST | None:
        if self.strip_private and node.name.startswith("_"):
            return None
        self.generic_visit(node)
        if not node.body:
            node.body = [ast.Expr(value=ast.Constant(value=...))]
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST | None:
        return self._transform_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST | None:
        return self._transform_func(node)

    def _transform_func(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> ast.AST | None:
        if self.strip_private and node.name.startswith("_") and not (
            node.name.startswith("__") and node.name.endswith("__")
        ):
            return None

        new_body: list[ast.stmt] = []
        doc = ast.get_docstring(node)
        if doc:
            new_body.append(ast.Expr(value=ast.Constant(value=doc.strip())))

        for stmt in node.body:
            if isinstance(stmt, (ast.If, ast.Try, ast.Raise, ast.Return, ast.For, ast.While)):
                condensed = self._condense_control_stmt(stmt)
                if condensed is not None:
                    new_body.append(condensed)

        if not new_body:
            new_body = [ast.Expr(value=ast.Constant(value=...))]

        node.body = new_body
        return node

    def _condense_control_stmt(self, stmt: ast.stmt) -> ast.stmt | None:
        """Condense inner blocks of control-flow statements while preserving raise/return guards."""
        if isinstance(stmt, ast.If):
            inner_body: list[ast.stmt] = [
                s for s in stmt.body if isinstance(s, (ast.Raise, ast.Return))
            ]
            if not inner_body:
                inner_body = [ast.Expr(value=ast.Constant(value=...))]
            orelse_body: list[ast.stmt] = [
                s for s in stmt.orelse if isinstance(s, (ast.Raise, ast.Return))
            ]
            if stmt.orelse and not orelse_body:
                orelse_body = [ast.Expr(value=ast.Constant(value=...))]
            return ast.If(
                test=stmt.test,
                body=inner_body,
                orelse=orelse_body,
            )
        if isinstance(stmt, ast.Try):
            handlers: list[ast.ExceptHandler] = []
            for handler in stmt.handlers:
                inner_h_body: list[ast.stmt] = [
                    s for s in handler.body if isinstance(s, (ast.Raise, ast.Return))
                ]
                if not inner_h_body:
                    inner_h_body = [ast.Expr(value=ast.Constant(value=...))]
                handlers.append(
                    ast.ExceptHandler(
                        type=handler.type,
                        name=handler.name,
                        body=inner_h_body,
                    )
                )
            return ast.Try(
                body=[ast.Expr(value=ast.Constant(value=...))],
                handlers=handlers,
                orelse=[],
                finalbody=[ast.Expr(value=ast.Constant(value=...))] if stmt.finalbody else [],
            )
        if isinstance(stmt, (ast.Raise, ast.Return)):
            return stmt
        if isinstance(stmt, (ast.For, ast.While)):
            if isinstance(stmt, ast.For):
                return ast.For(
                    target=stmt.target,
                    iter=stmt.iter,
                    body=[ast.Expr(value=ast.Constant(value=...))],
                    orelse=[],
                )
            return ast.While(
                test=stmt.test,
                body=[ast.Expr(value=ast.Constant(value=...))],
                orelse=[],
            )
        return None

