"""Python AST extractor using Tree-sitter.

Extracts functions, classes, imports, calls, and decorator patterns from
Python source code to build the code knowledge graph.

[INPUT]
- str (POS: Python source code)
- str (POS: file path for qualified names)

[OUTPUT]
- PythonParser: LanguageParser implementation for Python

[POS]
Tree-sitter-based Python code structure extractor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_graph.store import (
    ConfidenceTier,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from myrm_agent_harness.toolkits.code_graph.parser._base import ParseResult

if TYPE_CHECKING:
    from tree_sitter import Node as TSNode

logger = logging.getLogger(__name__)


class PythonParser:
    """Extracts Python code structure via Tree-sitter AST."""

    @property
    def language_id(self) -> str:
        return "python"

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".py"})

    def parse(self, source: str, file_path: str) -> ParseResult:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError:
            return ParseResult(language=self.language_id, errors=["tree-sitter not installed"])

        parser = get_parser("python")
        tree = parser.parse(source.encode("utf-8"))
        result = ParseResult(language=self.language_id)

        self._extract_module_node(file_path, source, result)
        self._walk(tree.root_node, file_path, "", result)
        return result

    def _extract_module_node(self, file_path: str, source: str, result: ParseResult) -> None:
        lines = source.count("\n") + 1
        result.nodes.append(GraphNode(
            kind=NodeKind.MODULE,
            name=file_path,
            qualified_name=file_path,
            file_path=file_path,
            line_start=1,
            line_end=lines,
            language=self.language_id,
        ))

    def _walk(
        self,
        node: TSNode,
        file_path: str,
        scope: str,
        result: ParseResult,
    ) -> None:
        if node.type == "function_definition":
            self._extract_function(node, file_path, scope, result)
        elif node.type == "class_definition":
            self._extract_class(node, file_path, scope, result)
        elif node.type == "import_statement":
            self._extract_import(node, file_path, scope, result)
        elif node.type == "import_from_statement":
            self._extract_import_from(node, file_path, scope, result)
        elif node.type == "call":
            self._extract_call(node, file_path, scope, result)
        else:
            for child in node.children:
                self._walk(child, file_path, scope, result)

    def _extract_function(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8") if name_node.text else ""
        qualified = f"{scope}.{name}" if scope else f"{file_path}::{name}"

        params = ""
        params_node = node.child_by_field_name("parameters")
        if params_node and params_node.text:
            params = params_node.text.decode("utf-8")

        ret = ""
        ret_node = node.child_by_field_name("return_type")
        if ret_node and ret_node.text:
            ret = ret_node.text.decode("utf-8")

        is_method = bool(scope and "::" in scope)
        kind = NodeKind.METHOD if is_method else NodeKind.FUNCTION

        decorators = self._get_decorators(node)
        is_test = name.startswith("test_") or "pytest" in decorators

        result.nodes.append(GraphNode(
            kind=kind,
            name=name,
            qualified_name=qualified,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=self.language_id,
            parent_name=scope.split("::")[-1] if scope else "",
            params=params,
            return_type=ret,
            modifiers=decorators,
            is_test=is_test,
        ))

        result.edges.append(GraphEdge(
            kind=EdgeKind.CONTAINS,
            source_qualified=scope if scope else file_path,
            target_qualified=qualified,
            file_path=file_path,
            line=node.start_point[0] + 1,
        ))

        if is_test:
            for tested in self._infer_tested_targets(name, scope):
                result.edges.append(GraphEdge(
                    kind=EdgeKind.TESTED_BY,
                    source_qualified=tested,
                    target_qualified=qualified,
                    file_path=file_path,
                    line=node.start_point[0] + 1,
                    confidence=0.6,
                    confidence_tier=ConfidenceTier.INFERRED,
                ))

        body_node = node.child_by_field_name("body")
        if body_node:
            for child in body_node.children:
                self._walk(child, file_path, qualified, result)

    def _extract_class(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8") if name_node.text else ""
        qualified = f"{scope}::{name}" if scope else f"{file_path}::{name}"

        result.nodes.append(GraphNode(
            kind=NodeKind.CLASS,
            name=name,
            qualified_name=qualified,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=self.language_id,
            parent_name=scope.split("::")[-1] if scope else "",
            modifiers=self._get_decorators(node),
        ))

        result.edges.append(GraphEdge(
            kind=EdgeKind.CONTAINS,
            source_qualified=scope if scope else file_path,
            target_qualified=qualified,
            file_path=file_path,
            line=node.start_point[0] + 1,
        ))

        bases = node.child_by_field_name("superclasses")
        if bases:
            for arg in bases.children:
                if arg.type == "identifier" and arg.text:
                    base_name = arg.text.decode("utf-8")
                    result.edges.append(GraphEdge(
                        kind=EdgeKind.INHERITS,
                        source_qualified=qualified,
                        target_qualified=base_name,
                        file_path=file_path,
                        line=node.start_point[0] + 1,
                        confidence=0.8,
                        confidence_tier=ConfidenceTier.INFERRED,
                    ))

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._walk(child, file_path, qualified, result)

    def _extract_import(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        for child in node.children:
            if child.type == "dotted_name" and child.text:
                module_name = child.text.decode("utf-8")
                src = scope if scope else file_path
                result.edges.append(GraphEdge(
                    kind=EdgeKind.IMPORTS_FROM,
                    source_qualified=src,
                    target_qualified=module_name,
                    file_path=file_path,
                    line=node.start_point[0] + 1,
                ))

    def _extract_import_from(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        module_node = node.child_by_field_name("module_name")
        if not module_node or not module_node.text:
            return
        module_name = module_node.text.decode("utf-8")
        src = scope if scope else file_path

        for child in node.children:
            if child.type == "import_list":
                for item in child.children:
                    if item.type == "identifier" and item.text:
                        imported = item.text.decode("utf-8")
                        result.edges.append(GraphEdge(
                            kind=EdgeKind.IMPORTS_FROM,
                            source_qualified=src,
                            target_qualified=f"{module_name}.{imported}",
                            file_path=file_path,
                            line=node.start_point[0] + 1,
                        ))

    def _extract_call(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        func_node = node.child_by_field_name("function")
        if not func_node or not func_node.text:
            return
        callee = func_node.text.decode("utf-8")
        src = scope if scope else file_path
        result.edges.append(GraphEdge(
            kind=EdgeKind.CALLS,
            source_qualified=src,
            target_qualified=callee,
            file_path=file_path,
            line=node.start_point[0] + 1,
            confidence=0.9,
            confidence_tier=ConfidenceTier.EXTRACTED,
        ))

    @staticmethod
    def _get_decorators(node: TSNode) -> str:
        decorators: list[str] = []
        for child in node.children:
            if child.type == "decorator" and child.text:
                decorators.append(child.text.decode("utf-8").strip())
        return ",".join(decorators)

    @staticmethod
    def _infer_tested_targets(test_name: str, scope: str) -> list[str]:
        if not test_name.startswith("test_"):
            return []
        target_name = test_name[5:]
        if scope:
            parts = scope.split("::")
            if len(parts) >= 2:
                module = parts[0]
                return [f"{module}::{target_name}"]
        return [target_name]
