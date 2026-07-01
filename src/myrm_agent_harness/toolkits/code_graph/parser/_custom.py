"""Declarative language extension via languages.toml.

Allows enterprise users to add custom language support without writing Python
by defining Tree-sitter query patterns in a TOML configuration file.

[INPUT]
- Path (POS: path to languages.toml configuration)

[OUTPUT]
- CustomParser: LanguageParser that uses declarative TOML-defined queries
- load_custom_parsers(): factory to load all custom parsers from config

[POS]
Extension point for enterprise private languages. Query patterns match
Tree-sitter AST nodes and extract them as graph nodes/edges.

## languages.toml Format

```toml
[languages.kotlin]
tree_sitter_language = "kotlin"
extensions = [".kt", ".kts"]

[[languages.kotlin.extractors]]
node_type = "function_declaration"
node_kind = "Function"
name_field = "name"
params_field = "parameters"
return_type_field = "return_type"

[[languages.kotlin.extractors]]
node_type = "class_declaration"
node_kind = "Class"
name_field = "name"
```
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_graph.store import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from myrm_agent_harness.toolkits.code_graph.parser._base import ParseResult

if TYPE_CHECKING:
    from tree_sitter import Node as TSNode

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractorRule:
    """A single extraction rule from languages.toml."""

    node_type: str
    node_kind: NodeKind
    name_field: str = "name"
    params_field: str = ""
    return_type_field: str = ""
    recurse_body: bool = True


class CustomParser:
    """Tree-sitter parser driven by declarative TOML rules."""

    def __init__(
        self,
        language: str,
        ts_language: str,
        extensions: frozenset[str],
        rules: list[ExtractorRule],
    ) -> None:
        self._language = language
        self._ts_language = ts_language
        self._extensions = extensions
        self._rules = rules
        self._rule_map: dict[str, ExtractorRule] = {r.node_type: r for r in rules}

    @property
    def language_id(self) -> str:
        return self._language

    @property
    def file_extensions(self) -> frozenset[str]:
        return self._extensions

    def parse(self, source: str, file_path: str) -> ParseResult:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError:
            return ParseResult(language=self.language_id, errors=["tree-sitter not installed"])

        parser = get_parser(self._ts_language)
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
        rule = self._rule_map.get(node.type)
        if rule:
            self._apply_rule(rule, node, file_path, scope, result)
        else:
            for child in node.children:
                self._walk(child, file_path, scope, result)

    def _apply_rule(
        self,
        rule: ExtractorRule,
        node: TSNode,
        file_path: str,
        scope: str,
        result: ParseResult,
    ) -> None:
        name_node = node.child_by_field_name(rule.name_field)
        if not name_node or not name_node.text:
            return
        name = name_node.text.decode("utf-8")
        qualified = f"{scope}::{name}" if scope else f"{file_path}::{name}"

        params = ""
        if rule.params_field:
            p = node.child_by_field_name(rule.params_field)
            if p and p.text:
                params = p.text.decode("utf-8")

        ret = ""
        if rule.return_type_field:
            r = node.child_by_field_name(rule.return_type_field)
            if r and r.text:
                ret = r.text.decode("utf-8")

        result.nodes.append(GraphNode(
            kind=rule.node_kind,
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

        if rule.recurse_body:
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    self._walk(child, file_path, qualified, result)


def load_custom_parsers(config_path: Path) -> list[CustomParser]:
    """Load custom language parsers from a languages.toml file."""
    if not config_path.exists():
        return []

    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            logger.warning("tomllib/tomli not available, cannot load languages.toml")
            return []

    try:
        with config_path.open("rb") as f:
            config = tomllib.load(f)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", config_path, exc)
        return []

    parsers: list[CustomParser] = []
    languages = config.get("languages", {})

    for lang_id, lang_config in languages.items():
        ts_lang = lang_config.get("tree_sitter_language", lang_id)
        extensions = frozenset(lang_config.get("extensions", []))
        if not extensions:
            continue

        rules: list[ExtractorRule] = []
        for ext_config in lang_config.get("extractors", []):
            kind_str = ext_config.get("node_kind", "Function")
            try:
                kind = NodeKind(kind_str)
            except ValueError:
                logger.warning("Unknown NodeKind '%s' in languages.toml", kind_str)
                continue

            rules.append(ExtractorRule(
                node_type=ext_config.get("node_type", ""),
                node_kind=kind,
                name_field=ext_config.get("name_field", "name"),
                params_field=ext_config.get("params_field", ""),
                return_type_field=ext_config.get("return_type_field", ""),
                recurse_body=ext_config.get("recurse_body", True),
            ))

        if rules:
            parsers.append(CustomParser(
                language=lang_id,
                ts_language=ts_lang,
                extensions=extensions,
                rules=rules,
            ))

    return parsers
