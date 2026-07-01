"""Parser factory — resolves file extension to the appropriate language parser.

[INPUT]
- str (POS: file extension or language identifier)

[OUTPUT]
- get_parser(): returns a LanguageParser for the given language
- parse_file(): convenience function to parse a file directly
- is_tree_sitter_available(): check if tree-sitter is installed
- register_custom_parsers(): load languages.toml custom parsers

[POS]
Entry point for multi-language AST parsing. Detects optional tree-sitter
dependency availability and falls back gracefully. Custom languages defined
via languages.toml are integrated as a fallback after built-in parsers.
"""

from __future__ import annotations

import logging
from pathlib import Path

from myrm_agent_harness.toolkits.code_graph.parser._base import (
    LanguageParser,
    ParseResult,
    SUPPORTED_LANGUAGES,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LanguageParser",
    "ParseResult",
    "SUPPORTED_LANGUAGES",
    "get_parser",
    "parse_file",
    "is_tree_sitter_available",
    "register_custom_parsers",
]

_parser_cache: dict[str, LanguageParser] = {}


def is_tree_sitter_available() -> bool:
    try:
        import tree_sitter_language_pack  # noqa: F401
        return True
    except ImportError:
        return False


def register_custom_parsers(config_path: Path) -> int:
    """Load custom parsers from languages.toml and register them.

    Returns the number of custom parsers successfully registered.
    """
    from myrm_agent_harness.toolkits.code_graph.parser._custom import load_custom_parsers

    parsers = load_custom_parsers(config_path)
    count = 0
    for p in parsers:
        _parser_cache[p.language_id] = p
        for ext in p.file_extensions:
            SUPPORTED_LANGUAGES[ext] = p.language_id
        count += 1
    if count:
        logger.info("Registered %d custom parser(s) from %s", count, config_path)
    return count


def get_parser(language: str) -> LanguageParser | None:
    """Get a parser for the given language identifier.

    Returns None if tree-sitter is not installed or language is not supported.
    """
    if language in _parser_cache:
        return _parser_cache[language]

    if not is_tree_sitter_available():
        logger.debug("tree-sitter-language-pack not installed, code graph parsing disabled")
        return None

    parser = _create_parser(language)
    if parser is not None:
        _parser_cache[language] = parser
    return parser


def _create_parser(language: str) -> LanguageParser | None:
    if language in ("python",):
        from myrm_agent_harness.toolkits.code_graph.parser._python import PythonParser
        return PythonParser()
    if language in ("javascript", "typescript"):
        from myrm_agent_harness.toolkits.code_graph.parser._javascript import JavaScriptParser
        return JavaScriptParser(language)
    if language in ("java",):
        from myrm_agent_harness.toolkits.code_graph.parser._java import JavaParser
        return JavaParser()
    if language in ("go",):
        from myrm_agent_harness.toolkits.code_graph.parser._go import GoParser
        return GoParser()
    if language in ("rust",):
        from myrm_agent_harness.toolkits.code_graph.parser._rust import RustParser
        return RustParser()
    if language in ("c", "cpp"):
        from myrm_agent_harness.toolkits.code_graph.parser._c_cpp import CCppParser
        return CCppParser(language)
    return None


def parse_file(file_path: str, source: str | None = None) -> ParseResult | None:
    """Parse a file and return extracted nodes and edges.

    Returns None if the file type is not supported or tree-sitter is not available.
    """
    ext = Path(file_path).suffix.lower()
    language = SUPPORTED_LANGUAGES.get(ext)
    if language is None:
        return None

    parser = get_parser(language)
    if parser is None:
        return None

    if source is None:
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.debug("Cannot read %s: %s", file_path, exc)
            return None

    return parser.parse(source, file_path)
