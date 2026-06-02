"""AST-aware parser for extracting code context (classes, functions) using tree-sitter.

[INPUT]
- tree_sitter::Parser, Language
- tree_sitter_python, tree_sitter_javascript, etc.

[OUTPUT]
- get_context_for_line: Extracts the hierarchical context (e.g., [class Foo -> def bar]) for a given line number.
- parse_file: Parses a file and returns a cached AST and query object.

[POS]
Provides AST parsing capabilities to enhance grep results with structural context.
Uses tree-sitter for robust, cross-platform parsing without heavy C-extension compilation on the user's machine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Try to import tree_sitter and languages. If they fail, we gracefully degrade.
try:
    import tree_sitter
    import tree_sitter_go
    import tree_sitter_java
    import tree_sitter_javascript
    import tree_sitter_python
    import tree_sitter_rust
    import tree_sitter_typescript

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False
    logger.warning("tree-sitter or its language packs are not installed. AST context will be disabled.")

_LANGUAGES: dict[str, Any] = {}
_QUERIES: dict[str, Any] = {}

def _init_global_languages() -> None:
    """Initialize tree-sitter languages and their respective queries globally."""
    if not HAS_TREE_SITTER or _LANGUAGES:
        return

    try:
        _LANGUAGES["python"] = tree_sitter.Language(tree_sitter_python.language())
        _QUERIES["python"] = tree_sitter.Query(_LANGUAGES["python"], """
            (class_definition name: (identifier) @class.name) @class.def
            (function_definition name: (identifier) @function.name) @function.def
        """)

        _LANGUAGES["javascript"] = tree_sitter.Language(tree_sitter_javascript.language())
        _QUERIES["javascript"] = tree_sitter.Query(_LANGUAGES["javascript"], """
            (class_declaration name: (identifier) @class.name) @class.def
            (function_declaration name: (identifier) @function.name) @function.def
            (method_definition name: (property_identifier) @method.name) @method.def
            (lexical_declaration (variable_declarator name: (identifier) @function.name value: (arrow_function))) @function.def
        """)

        _LANGUAGES["typescript"] = tree_sitter.Language(tree_sitter_typescript.language_typescript())
        _QUERIES["typescript"] = tree_sitter.Query(_LANGUAGES["typescript"], """
            (class_declaration name: (type_identifier) @class.name) @class.def
            (function_declaration name: (identifier) @function.name) @function.def
            (method_definition name: (property_identifier) @method.name) @method.def
            (lexical_declaration (variable_declarator name: (identifier) @function.name value: (arrow_function))) @function.def
            (interface_declaration name: (type_identifier) @interface.name) @interface.def
        """)

        _LANGUAGES["go"] = tree_sitter.Language(tree_sitter_go.language())
        _QUERIES["go"] = tree_sitter.Query(_LANGUAGES["go"], """
            (type_declaration (type_spec name: (type_identifier) @type.name)) @type.def
            (function_declaration name: (identifier) @function.name) @function.def
            (method_declaration name: (field_identifier) @method.name) @method.def
        """)

        _LANGUAGES["rust"] = tree_sitter.Language(tree_sitter_rust.language())
        _QUERIES["rust"] = tree_sitter.Query(_LANGUAGES["rust"], """
            (struct_item name: (type_identifier) @struct.name) @struct.def
            (impl_item type: (type_identifier) @impl.name) @impl.def
            (function_item name: (identifier) @function.name) @function.def
        """)

        _LANGUAGES["java"] = tree_sitter.Language(tree_sitter_java.language())
        _QUERIES["java"] = tree_sitter.Query(_LANGUAGES["java"], """
            (class_declaration name: (identifier) @class.name) @class.def
            (method_declaration name: (identifier) @method.name) @method.def
            (interface_declaration name: (identifier) @interface.name) @interface.def
        """)
    except Exception as e:
        logger.warning(f"Failed to initialize tree-sitter languages: {e}")

# Initialize globally once
_init_global_languages()


@dataclass
class SymbolNode:
    """Represents a structural symbol (class, function, method) in the AST."""

    type: str  # e.g., "class", "function", "method"
    name: str
    start_line: int  # 1-indexed
    end_line: int  # 1-indexed


class ASTParser:
    """Parser for extracting structural context from code files.

    This class should be instantiated per grep format operation to avoid caching
    stale ASTs if the file is modified between grep calls.
    """

    def __init__(self) -> None:
        self._parsed_files: dict[Path, tuple[Any, Any] | None] = {}
        self._symbols_cache: dict[Path, list[SymbolNode]] = {}

    def _get_language_for_file(self, file_path: Path) -> str | None:
        """Determine the language based on file extension."""
        ext = file_path.suffix.lower()
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
        }
        return mapping.get(ext)

    def _parse_file(self, file_path: Path) -> tuple[Any, Any] | None:
        """Parse a file and return its AST tree and query object. Cached for performance."""
        if file_path in self._parsed_files:
            return self._parsed_files[file_path]

        if not HAS_TREE_SITTER:
            self._parsed_files[file_path] = None
            return None

        # Large file circuit breaker: skip parsing if file > 1MB to prevent OOM
        try:
            if file_path.stat().st_size > 1024 * 1024:
                logger.debug(f"Skipping AST parsing for large file: {file_path}")
                self._parsed_files[file_path] = None
                return None
        except OSError:
            self._parsed_files[file_path] = None
            return None

        lang_name = self._get_language_for_file(file_path)
        if not lang_name or lang_name not in _LANGUAGES:
            self._parsed_files[file_path] = None
            return None

        try:
            content = file_path.read_bytes()
            parser = tree_sitter.Parser(_LANGUAGES[lang_name])
            tree = parser.parse(content)
            query = _QUERIES[lang_name]
            result = (tree, query)
            self._parsed_files[file_path] = result
            return result
        except Exception as e:
            logger.debug(f"Failed to parse {file_path} with tree-sitter: {e}")
            self._parsed_files[file_path] = None
            return None

    def get_symbols(self, file_path: Path) -> list[SymbolNode]:
        """Extract all structural symbols from a file."""
        if file_path in self._symbols_cache:
            return self._symbols_cache[file_path]

        parsed = self._parse_file(file_path)
        if not parsed:
            self._symbols_cache[file_path] = []
            return []

        tree, query = parsed
        symbols: list[SymbolNode] = []

        try:
            # In tree-sitter 0.22+, we use QueryCursor
            cursor = tree_sitter.QueryCursor(query)
            matches = cursor.matches(tree.root_node)
            for match in matches:
                # match is a tuple: (pattern_index, dict of captures)
                captures = match[1] if isinstance(match, tuple) else match

                # We expect pairs of .def and .name captures
                def_node = None
                name_node = None
                symbol_type = "unknown"

                for capture_name, nodes in captures.items():
                    if not nodes:
                        continue
                    node = nodes[0] if isinstance(nodes, list) else nodes

                    if capture_name.endswith(".def"):
                        def_node = node
                        symbol_type = capture_name.split(".")[0]
                    elif capture_name.endswith(".name"):
                        name_node = node

                if def_node and name_node:
                    # tree-sitter lines are 0-indexed, we want 1-indexed
                    symbols.append(
                        SymbolNode(
                            type=symbol_type,
                            name=name_node.text.decode("utf-8", errors="replace") if name_node.text else "",
                            start_line=def_node.start_point[0] + 1,
                            end_line=def_node.end_point[0] + 1,
                        )
                    )
        except Exception as e:
            logger.debug(f"Error extracting symbols from {file_path}: {e}")

        # Sort symbols by start line, then by end line (descending) so outer scopes come first
        symbols.sort(key=lambda s: (s.start_line, -s.end_line))
        self._symbols_cache[file_path] = symbols
        return symbols

    def get_context_for_line(self, file_path: Path, line_number: int) -> str | None:
        """Get the hierarchical context (e.g., class -> method) for a specific line."""
        symbols = self.get_symbols(file_path)
        if not symbols:
            return None

        # Find all symbols that enclose the line_number
        enclosing_symbols = [
            s for s in symbols if s.start_line <= line_number <= s.end_line
        ]

        if not enclosing_symbols:
            return None

        # Build the hierarchy string, e.g., "class Foo -> def bar"
        parts = []
        for sym in enclosing_symbols:
            prefix = "def" if sym.type in ("function", "method") else sym.type
            parts.append(f"{prefix} {sym.name}")

        return " -> ".join(parts)


# Global instance
_ast_parser = ASTParser()


def get_context_for_line(file_path: Path | str, line_number: int) -> str | None:
    """Convenience function to get context for a line."""
    if isinstance(file_path, str):
        file_path = Path(file_path)
    return _ast_parser.get_context_for_line(file_path, line_number)
