"""JavaScript/TypeScript AST extractor using Tree-sitter.

Extracts functions, classes, imports, calls, and export patterns from
JS/TS source code to build the code knowledge graph.

[INPUT]
- str (POS: JS/TS source code)
- str (POS: file path for qualified names)

[OUTPUT]
- JavaScriptParser: LanguageParser implementation for JS/TS

[POS]
Tree-sitter-based JS/TS code structure extractor.
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

_TS_LANGUAGE_MAP = {
    "javascript": "javascript",
    "typescript": "typescript",
}


class JavaScriptParser:
    """Extracts JS/TS code structure via Tree-sitter AST."""

    def __init__(self, language: str = "javascript") -> None:
        self._language = language

    @property
    def language_id(self) -> str:
        return self._language

    @property
    def file_extensions(self) -> frozenset[str]:
        if self._language == "typescript":
            return frozenset({".ts", ".tsx"})
        return frozenset({".js", ".jsx"})

    def parse(self, source: str, file_path: str) -> ParseResult:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError:
            return ParseResult(language=self.language_id, errors=["tree-sitter not installed"])

        ts_lang = _TS_LANGUAGE_MAP.get(self._language, self._language)
        parser = get_parser(ts_lang)
        tree = parser.parse(source.encode("utf-8"))
        result = ParseResult(language=self.language_id)

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

        self._walk(tree.root_node, file_path, "", result)
        return result

    def _walk(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        if node.type in ("function_declaration", "method_definition", "arrow_function"):
            self._extract_function(node, file_path, scope, result)
        elif node.type == "class_declaration":
            self._extract_class(node, file_path, scope, result)
        elif node.type in ("import_statement", "import_declaration"):
            self._extract_import(node, file_path, scope, result)
        elif node.type == "call_expression":
            self._extract_call(node, file_path, scope, result)
        elif node.type in ("interface_declaration",) and self._language == "typescript":
            self._extract_interface(node, file_path, scope, result)
        else:
            for child in node.children:
                self._walk(child, file_path, scope, result)

    def _extract_function(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = self._get_name(node)
        if not name and node.type == "arrow_function":
            parent = node.parent
            if parent and parent.type in ("variable_declarator", "pair"):
                name = self._get_name(parent)
        if not name:
            return

        qualified = f"{scope}::{name}" if scope else f"{file_path}::{name}"
        is_method = node.type == "method_definition"

        params = ""
        params_node = node.child_by_field_name("parameters")
        if params_node and params_node.text:
            params = params_node.text.decode("utf-8")

        ret = ""
        ret_node = node.child_by_field_name("return_type")
        if ret_node and ret_node.text:
            ret = ret_node.text.decode("utf-8")

        result.nodes.append(GraphNode(
            kind=NodeKind.METHOD if is_method else NodeKind.FUNCTION,
            name=name,
            qualified_name=qualified,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=self.language_id,
            parent_name=scope.split("::")[-1] if scope else "",
            params=params,
            return_type=ret,
            is_test=name.startswith("test") or ".test." in file_path or ".spec." in file_path,
        ))

        result.edges.append(GraphEdge(
            kind=EdgeKind.CONTAINS,
            source_qualified=scope if scope else file_path,
            target_qualified=qualified,
            file_path=file_path,
            line=node.start_point[0] + 1,
        ))

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._walk(child, file_path, qualified, result)

    def _extract_class(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = self._get_name(node)
        if not name:
            return
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
        ))

        result.edges.append(GraphEdge(
            kind=EdgeKind.CONTAINS,
            source_qualified=scope if scope else file_path,
            target_qualified=qualified,
            file_path=file_path,
            line=node.start_point[0] + 1,
        ))

        heritage = node.child_by_field_name("heritage")
        if heritage:
            for clause in heritage.children:
                if clause.type in ("extends_clause", "implements_clause") and clause.text:
                    base = clause.text.decode("utf-8").split()[-1].strip()
                    edge_kind = EdgeKind.INHERITS if "extends" in (clause.type or "") else EdgeKind.IMPLEMENTS
                    result.edges.append(GraphEdge(
                        kind=edge_kind,
                        source_qualified=qualified,
                        target_qualified=base,
                        file_path=file_path,
                        line=node.start_point[0] + 1,
                        confidence=0.8,
                        confidence_tier=ConfidenceTier.INFERRED,
                    ))

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._walk(child, file_path, qualified, result)

    def _extract_interface(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = self._get_name(node)
        if not name:
            return
        qualified = f"{scope}::{name}" if scope else f"{file_path}::{name}"

        result.nodes.append(GraphNode(
            kind=NodeKind.INTERFACE,
            name=name,
            qualified_name=qualified,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=self.language_id,
        ))

        result.edges.append(GraphEdge(
            kind=EdgeKind.CONTAINS,
            source_qualified=scope if scope else file_path,
            target_qualified=qualified,
            file_path=file_path,
            line=node.start_point[0] + 1,
        ))

    def _extract_import(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        source_node = node.child_by_field_name("source")
        if not source_node or not source_node.text:
            return
        module = source_node.text.decode("utf-8").strip("'\"")
        src = scope if scope else file_path

        result.edges.append(GraphEdge(
            kind=EdgeKind.IMPORTS_FROM,
            source_qualified=src,
            target_qualified=module,
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
    def _get_name(node: TSNode) -> str:
        name_node = node.child_by_field_name("name")
        if name_node and name_node.text:
            return name_node.text.decode("utf-8")
        return ""
