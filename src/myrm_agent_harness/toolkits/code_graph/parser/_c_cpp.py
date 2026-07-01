"""C/C++ AST extractor using Tree-sitter.

[INPUT]
- str (POS: C/C++ source code)
- str (POS: file path for qualified names)

[OUTPUT]
- CCppParser: LanguageParser implementation for C and C++

[POS]
Tree-sitter-based C/C++ code structure extractor — functions, structs, classes, includes.
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


class CCppParser:
    """Extracts C/C++ code structure via Tree-sitter AST."""

    def __init__(self, language: str = "c") -> None:
        self._language = language

    @property
    def language_id(self) -> str:
        return self._language

    @property
    def file_extensions(self) -> frozenset[str]:
        if self._language == "cpp":
            return frozenset({".cpp", ".cc", ".cxx", ".hpp", ".hh"})
        return frozenset({".c", ".h"})

    def parse(self, source: str, file_path: str) -> ParseResult:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError:
            return ParseResult(language=self.language_id, errors=["tree-sitter not installed"])

        parser = get_parser(self._language)
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
        if node.type == "function_definition":
            self._extract_function(node, file_path, scope, result)
        elif node.type == "struct_specifier":
            self._extract_struct(node, file_path, scope, result)
        elif node.type == "class_specifier":
            self._extract_class(node, file_path, scope, result)
        elif node.type == "preproc_include":
            self._extract_include(node, file_path, result)
        elif node.type == "call_expression":
            self._extract_call(node, file_path, scope, result)
        elif node.type == "namespace_definition":
            self._extract_namespace(node, file_path, scope, result)
        else:
            for child in node.children:
                self._walk(child, file_path, scope, result)

    def _extract_function(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        declarator = node.child_by_field_name("declarator")
        if not declarator:
            return
        name = self._get_declarator_name(declarator)
        if not name:
            return
        qualified = f"{scope}::{name}" if scope else f"{file_path}::{name}"

        params = ""
        params_node = declarator.child_by_field_name("parameters")
        if params_node and params_node.text:
            params = params_node.text.decode("utf-8")

        ret = ""
        type_node = node.child_by_field_name("type")
        if type_node and type_node.text:
            ret = type_node.text.decode("utf-8")

        result.nodes.append(GraphNode(
            kind=NodeKind.FUNCTION,
            name=name,
            qualified_name=qualified,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=self.language_id,
            parent_name=scope.split("::")[-1] if scope else "",
            params=params,
            return_type=ret,
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

    def _extract_struct(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
        if not name:
            return
        qualified = f"{scope}::{name}" if scope else f"{file_path}::{name}"

        result.nodes.append(GraphNode(
            kind=NodeKind.STRUCT,
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

    def _extract_class(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
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
        ))

        result.edges.append(GraphEdge(
            kind=EdgeKind.CONTAINS,
            source_qualified=scope if scope else file_path,
            target_qualified=qualified,
            file_path=file_path,
            line=node.start_point[0] + 1,
        ))

        for child in node.children:
            if child.type == "base_class_clause":
                for base_child in child.children:
                    if base_child.type == "type_identifier" and base_child.text:
                        result.edges.append(GraphEdge(
                            kind=EdgeKind.INHERITS,
                            source_qualified=qualified,
                            target_qualified=base_child.text.decode("utf-8"),
                            file_path=file_path,
                            line=node.start_point[0] + 1,
                            confidence=0.8,
                            confidence_tier=ConfidenceTier.INFERRED,
                        ))

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._walk(child, file_path, qualified, result)

    def _extract_namespace(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
        ns_scope = f"{scope}::{name}" if scope and name else (f"{file_path}::{name}" if name else scope)

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._walk(child, file_path, ns_scope, result)

    def _extract_include(
        self, node: TSNode, file_path: str, result: ParseResult,
    ) -> None:
        path_node = node.child_by_field_name("path")
        if path_node and path_node.text:
            include_path = path_node.text.decode("utf-8").strip('"<>')
            result.edges.append(GraphEdge(
                kind=EdgeKind.IMPORTS_FROM,
                source_qualified=file_path,
                target_qualified=include_path,
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

    def _get_declarator_name(self, node: TSNode) -> str:
        if node.type == "identifier" and node.text:
            return node.text.decode("utf-8")
        if node.type in ("function_declarator", "pointer_declarator"):
            declarator = node.child_by_field_name("declarator")
            if declarator:
                return self._get_declarator_name(declarator)
        name_node = node.child_by_field_name("name")
        if name_node and name_node.text:
            return name_node.text.decode("utf-8")
        return ""


def _get_name(node: TSNode) -> str:
    name_node = node.child_by_field_name("name")
    if name_node and name_node.text:
        return name_node.text.decode("utf-8")
    return ""
