"""Go AST extractor using Tree-sitter.

[INPUT]
- str (POS: Go source code)
- str (POS: file path for qualified names)

[OUTPUT]
- GoParser: LanguageParser implementation for Go

[POS]
Tree-sitter-based Go code structure extractor — functions, structs, interfaces, imports.
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


class GoParser:
    """Extracts Go code structure via Tree-sitter AST."""

    @property
    def language_id(self) -> str:
        return "go"

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".go"})

    def parse(self, source: str, file_path: str) -> ParseResult:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError:
            return ParseResult(language=self.language_id, errors=["tree-sitter not installed"])

        parser = get_parser("go")
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

        self._walk(tree.root_node, file_path, result)
        return result

    def _walk(self, node: TSNode, file_path: str, result: ParseResult) -> None:
        if node.type == "function_declaration":
            self._extract_function(node, file_path, result)
        elif node.type == "method_declaration":
            self._extract_method(node, file_path, result)
        elif node.type == "type_declaration":
            self._extract_type_decl(node, file_path, result)
        elif node.type == "import_declaration":
            self._extract_imports(node, file_path, result)
        elif node.type == "call_expression":
            self._extract_call(node, file_path, "", result)
        else:
            for child in node.children:
                self._walk(child, file_path, result)

    def _extract_function(
        self, node: TSNode, file_path: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
        if not name:
            return
        qualified = f"{file_path}::{name}"

        params = ""
        params_node = node.child_by_field_name("parameters")
        if params_node and params_node.text:
            params = params_node.text.decode("utf-8")

        ret = ""
        ret_node = node.child_by_field_name("result")
        if ret_node and ret_node.text:
            ret = ret_node.text.decode("utf-8")

        is_test = name.startswith("Test") or name.startswith("Benchmark")

        result.nodes.append(GraphNode(
            kind=NodeKind.FUNCTION,
            name=name,
            qualified_name=qualified,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=self.language_id,
            params=params,
            return_type=ret,
            is_test=is_test,
        ))

        result.edges.append(GraphEdge(
            kind=EdgeKind.CONTAINS,
            source_qualified=file_path,
            target_qualified=qualified,
            file_path=file_path,
            line=node.start_point[0] + 1,
        ))

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "call_expression":
                    self._extract_call(child, file_path, qualified, result)

    def _extract_method(
        self, node: TSNode, file_path: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
        if not name:
            return

        receiver = ""
        recv_node = node.child_by_field_name("receiver")
        if recv_node and recv_node.text:
            receiver = recv_node.text.decode("utf-8").strip("()")
            parts = receiver.split()
            receiver = parts[-1] if parts else receiver
            receiver = receiver.strip("*")

        qualified = f"{file_path}::{receiver}.{name}" if receiver else f"{file_path}::{name}"

        result.nodes.append(GraphNode(
            kind=NodeKind.METHOD,
            name=name,
            qualified_name=qualified,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=self.language_id,
            parent_name=receiver,
        ))

        result.edges.append(GraphEdge(
            kind=EdgeKind.CONTAINS,
            source_qualified=file_path,
            target_qualified=qualified,
            file_path=file_path,
            line=node.start_point[0] + 1,
        ))

    def _extract_type_decl(
        self, node: TSNode, file_path: str, result: ParseResult,
    ) -> None:
        for child in node.children:
            if child.type == "type_spec":
                self._extract_type_spec(child, file_path, result)

    def _extract_type_spec(
        self, node: TSNode, file_path: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
        if not name:
            return
        qualified = f"{file_path}::{name}"

        type_node = node.child_by_field_name("type")
        if type_node and type_node.type == "struct_type":
            kind = NodeKind.STRUCT
        elif type_node and type_node.type == "interface_type":
            kind = NodeKind.INTERFACE
        else:
            kind = NodeKind.TYPE

        result.nodes.append(GraphNode(
            kind=kind,
            name=name,
            qualified_name=qualified,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=self.language_id,
        ))

        result.edges.append(GraphEdge(
            kind=EdgeKind.CONTAINS,
            source_qualified=file_path,
            target_qualified=qualified,
            file_path=file_path,
            line=node.start_point[0] + 1,
        ))

    def _extract_imports(
        self, node: TSNode, file_path: str, result: ParseResult,
    ) -> None:
        for child in node.children:
            if child.type == "import_spec":
                path_node = child.child_by_field_name("path")
                if path_node and path_node.text:
                    module = path_node.text.decode("utf-8").strip('"')
                    result.edges.append(GraphEdge(
                        kind=EdgeKind.IMPORTS_FROM,
                        source_qualified=file_path,
                        target_qualified=module,
                        file_path=file_path,
                        line=child.start_point[0] + 1,
                    ))
            elif child.type == "import_spec_list":
                self._extract_imports(child, file_path, result)
            elif child.type == "interpreted_string_literal" and child.text:
                module = child.text.decode("utf-8").strip('"')
                result.edges.append(GraphEdge(
                    kind=EdgeKind.IMPORTS_FROM,
                    source_qualified=file_path,
                    target_qualified=module,
                    file_path=file_path,
                    line=child.start_point[0] + 1,
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


def _get_name(node: TSNode) -> str:
    name_node = node.child_by_field_name("name")
    if name_node and name_node.text:
        return name_node.text.decode("utf-8")
    return ""
