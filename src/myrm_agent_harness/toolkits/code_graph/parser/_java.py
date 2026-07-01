"""Java AST extractor using Tree-sitter.

[INPUT]
- str (POS: Java source code)
- str (POS: file path for qualified names)

[OUTPUT]
- JavaParser: LanguageParser implementation for Java

[POS]
Tree-sitter-based Java code structure extractor — classes, methods, imports, annotations.
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


class JavaParser:
    """Extracts Java code structure via Tree-sitter AST."""

    @property
    def language_id(self) -> str:
        return "java"

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".java"})

    def parse(self, source: str, file_path: str) -> ParseResult:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError:
            return ParseResult(language=self.language_id, errors=["tree-sitter not installed"])

        parser = get_parser("java")
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
        if node.type in ("class_declaration", "enum_declaration"):
            self._extract_class(node, file_path, scope, result)
        elif node.type == "interface_declaration":
            self._extract_interface(node, file_path, scope, result)
        elif node.type in ("method_declaration", "constructor_declaration"):
            self._extract_method(node, file_path, scope, result)
        elif node.type == "import_declaration":
            self._extract_import(node, file_path, result)
        elif node.type == "method_invocation":
            self._extract_call(node, file_path, scope, result)
        else:
            for child in node.children:
                self._walk(child, file_path, scope, result)

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
            parent_name=scope.split("::")[-1] if scope else "",
        ))

        result.edges.append(GraphEdge(
            kind=EdgeKind.CONTAINS,
            source_qualified=scope if scope else file_path,
            target_qualified=qualified,
            file_path=file_path,
            line=node.start_point[0] + 1,
        ))

        self._extract_superclass(node, qualified, file_path, result)
        self._extract_interfaces(node, qualified, file_path, result)

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._walk(child, file_path, qualified, result)

    def _extract_interface(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
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

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._walk(child, file_path, qualified, result)

    def _extract_method(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
        if not name:
            name = "<init>" if node.type == "constructor_declaration" else ""
        if not name:
            return
        qualified = f"{scope}::{name}" if scope else f"{file_path}::{name}"

        params = ""
        params_node = node.child_by_field_name("parameters")
        if params_node and params_node.text:
            params = params_node.text.decode("utf-8")

        ret = ""
        ret_node = node.child_by_field_name("type")
        if ret_node and ret_node.text:
            ret = ret_node.text.decode("utf-8")

        annotations = _get_annotations(node)
        is_test = "@Test" in annotations or "@ParameterizedTest" in annotations

        result.nodes.append(GraphNode(
            kind=NodeKind.METHOD,
            name=name,
            qualified_name=qualified,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=self.language_id,
            parent_name=scope.split("::")[-1] if scope else "",
            params=params,
            return_type=ret,
            modifiers=annotations,
            is_test=is_test,
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

    def _extract_import(
        self, node: TSNode, file_path: str, result: ParseResult,
    ) -> None:
        if node.text:
            raw = node.text.decode("utf-8")
            module = raw.replace("import ", "").replace("static ", "").rstrip(";").strip()
            result.edges.append(GraphEdge(
                kind=EdgeKind.IMPORTS_FROM,
                source_qualified=file_path,
                target_qualified=module,
                file_path=file_path,
                line=node.start_point[0] + 1,
            ))

    def _extract_call(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node or not name_node.text:
            return
        callee = name_node.text.decode("utf-8")
        obj_node = node.child_by_field_name("object")
        if obj_node and obj_node.text:
            callee = f"{obj_node.text.decode('utf-8')}.{callee}"
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
    def _extract_superclass(
        node: TSNode, qualified: str, file_path: str, result: ParseResult,
    ) -> None:
        sc = node.child_by_field_name("superclass")
        if sc and sc.text:
            base = sc.text.decode("utf-8").strip()
            result.edges.append(GraphEdge(
                kind=EdgeKind.INHERITS,
                source_qualified=qualified,
                target_qualified=base,
                file_path=file_path,
                line=node.start_point[0] + 1,
                confidence=0.8,
                confidence_tier=ConfidenceTier.INFERRED,
            ))

    @staticmethod
    def _extract_interfaces(
        node: TSNode, qualified: str, file_path: str, result: ParseResult,
    ) -> None:
        interfaces = node.child_by_field_name("interfaces")
        if not interfaces:
            return
        for child in interfaces.children:
            if child.type == "type_identifier" and child.text:
                result.edges.append(GraphEdge(
                    kind=EdgeKind.IMPLEMENTS,
                    source_qualified=qualified,
                    target_qualified=child.text.decode("utf-8"),
                    file_path=file_path,
                    line=node.start_point[0] + 1,
                    confidence=0.8,
                    confidence_tier=ConfidenceTier.INFERRED,
                ))


def _get_name(node: TSNode) -> str:
    name_node = node.child_by_field_name("name")
    if name_node and name_node.text:
        return name_node.text.decode("utf-8")
    return ""


def _get_annotations(node: TSNode) -> str:
    annotations: list[str] = []
    for child in node.children:
        if child.type in ("annotation", "marker_annotation") and child.text:
            annotations.append(child.text.decode("utf-8").strip())
    return ",".join(annotations)
