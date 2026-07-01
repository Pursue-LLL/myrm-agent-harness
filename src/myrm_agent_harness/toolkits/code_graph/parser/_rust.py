"""Rust AST extractor using Tree-sitter.

[INPUT]
- str (POS: Rust source code)
- str (POS: file path for qualified names)

[OUTPUT]
- RustParser: LanguageParser implementation for Rust

[POS]
Tree-sitter-based Rust code structure extractor — functions, structs, traits, impl blocks.
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


class RustParser:
    """Extracts Rust code structure via Tree-sitter AST."""

    @property
    def language_id(self) -> str:
        return "rust"

    @property
    def file_extensions(self) -> frozenset[str]:
        return frozenset({".rs"})

    def parse(self, source: str, file_path: str) -> ParseResult:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError:
            return ParseResult(language=self.language_id, errors=["tree-sitter not installed"])

        parser = get_parser("rust")
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
        if node.type == "function_item":
            self._extract_function(node, file_path, scope, result)
        elif node.type == "struct_item":
            self._extract_struct(node, file_path, scope, result)
        elif node.type == "trait_item":
            self._extract_trait(node, file_path, scope, result)
        elif node.type == "impl_item":
            self._extract_impl(node, file_path, scope, result)
        elif node.type == "use_declaration":
            self._extract_use(node, file_path, result)
        elif node.type == "call_expression":
            self._extract_call(node, file_path, scope, result)
        elif node.type == "enum_item":
            self._extract_enum(node, file_path, scope, result)
        else:
            for child in node.children:
                self._walk(child, file_path, scope, result)

    def _extract_function(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
        if not name:
            return
        qualified = f"{scope}::{name}" if scope else f"{file_path}::{name}"
        is_method = bool(scope)
        is_test = _has_test_attribute(node)

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

    def _extract_trait(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
        if not name:
            return
        qualified = f"{scope}::{name}" if scope else f"{file_path}::{name}"

        result.nodes.append(GraphNode(
            kind=NodeKind.TRAIT,
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

    def _extract_impl(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        type_node = node.child_by_field_name("type")
        if not type_node or not type_node.text:
            return
        impl_type = type_node.text.decode("utf-8")
        impl_scope = f"{file_path}::{impl_type}"

        trait_node = node.child_by_field_name("trait")
        if trait_node and trait_node.text:
            trait_name = trait_node.text.decode("utf-8")
            result.edges.append(GraphEdge(
                kind=EdgeKind.IMPLEMENTS,
                source_qualified=impl_scope,
                target_qualified=trait_name,
                file_path=file_path,
                line=node.start_point[0] + 1,
                confidence=0.9,
                confidence_tier=ConfidenceTier.EXTRACTED,
            ))

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._walk(child, file_path, impl_scope, result)

    def _extract_enum(
        self, node: TSNode, file_path: str, scope: str, result: ParseResult,
    ) -> None:
        name = _get_name(node)
        if not name:
            return
        qualified = f"{scope}::{name}" if scope else f"{file_path}::{name}"

        result.nodes.append(GraphNode(
            kind=NodeKind.TYPE,
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

    def _extract_use(
        self, node: TSNode, file_path: str, result: ParseResult,
    ) -> None:
        if node.text:
            raw = node.text.decode("utf-8")
            module = raw.replace("use ", "").rstrip(";").strip()
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


def _has_test_attribute(node: TSNode) -> bool:
    for child in node.children:
        if child.type == "attribute_item" and child.text:
            text = child.text.decode("utf-8")
            if "test" in text:
                return True
    return False
