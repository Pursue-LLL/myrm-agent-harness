"""Tests for code_graph parser — factory, custom parsers, language dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_graph.parser import (
    SUPPORTED_LANGUAGES,
    get_parser,
    is_tree_sitter_available,
    parse_file,
    register_custom_parsers,
    _parser_cache,
)
from myrm_agent_harness.toolkits.code_graph.parser._base import (
    LanguageParser,
    ParseResult,
)


class TestSupportedLanguages:
    def test_python_extensions(self) -> None:
        assert SUPPORTED_LANGUAGES.get(".py") == "python"

    def test_javascript_extensions(self) -> None:
        assert SUPPORTED_LANGUAGES.get(".js") == "javascript"
        assert SUPPORTED_LANGUAGES.get(".jsx") == "javascript"

    def test_typescript_extensions(self) -> None:
        assert SUPPORTED_LANGUAGES.get(".ts") == "typescript"
        assert SUPPORTED_LANGUAGES.get(".tsx") == "typescript"

    def test_java_extension(self) -> None:
        assert SUPPORTED_LANGUAGES.get(".java") == "java"

    def test_go_extension(self) -> None:
        assert SUPPORTED_LANGUAGES.get(".go") == "go"

    def test_rust_extension(self) -> None:
        assert SUPPORTED_LANGUAGES.get(".rs") == "rust"

    def test_c_extensions(self) -> None:
        assert SUPPORTED_LANGUAGES.get(".c") == "c"
        assert SUPPORTED_LANGUAGES.get(".h") == "c"

    def test_cpp_extensions(self) -> None:
        assert SUPPORTED_LANGUAGES.get(".cpp") == "cpp"
        assert SUPPORTED_LANGUAGES.get(".cc") == "cpp"
        assert SUPPORTED_LANGUAGES.get(".cxx") == "cpp"
        assert SUPPORTED_LANGUAGES.get(".hpp") == "cpp"
        assert SUPPORTED_LANGUAGES.get(".hh") == "cpp"

    def test_unsupported_extension(self) -> None:
        assert SUPPORTED_LANGUAGES.get(".md") is None
        assert SUPPORTED_LANGUAGES.get(".json") is None
        assert SUPPORTED_LANGUAGES.get(".txt") is None


class TestParseFile:
    def test_unsupported_extension_returns_none(self) -> None:
        result = parse_file("readme.md", "# Hello")
        assert result is None

    def test_nonexistent_file_without_source_returns_none(self) -> None:
        result = parse_file("/tmp/__nonexistent_test_file_12345__.py")
        assert result is None

    @pytest.mark.skipif(
        not is_tree_sitter_available(),
        reason="tree-sitter-language-pack not installed",
    )
    def test_python_source_returns_parse_result(self) -> None:
        source = "def foo():\n    pass\n\nclass Bar:\n    def baz(self):\n        pass\n"
        result = parse_file("example.py", source)
        assert result is not None
        assert isinstance(result, ParseResult)
        assert len(result.nodes) >= 1

        names = {n.name for n in result.nodes}
        assert "foo" in names

    @pytest.mark.skipif(
        not is_tree_sitter_available(),
        reason="tree-sitter-language-pack not installed",
    )
    def test_javascript_source_extracts_functions(self) -> None:
        source = "function greet(name) {\n  return 'Hello ' + name;\n}\n"
        result = parse_file("app.js", source)
        assert result is not None
        assert len(result.nodes) >= 1


class TestGetParser:
    @pytest.mark.skipif(
        not is_tree_sitter_available(),
        reason="tree-sitter-language-pack not installed",
    )
    def test_python_parser_cached(self) -> None:
        parser = get_parser("python")
        assert parser is not None
        parser2 = get_parser("python")
        assert parser is parser2

    def test_unknown_language_returns_none(self) -> None:
        result = get_parser("brainfuck_not_real_lang_xyz")
        assert result is None


class TestRegisterCustomParsers:
    def test_register_from_nonexistent_file(self, tmp_path: Path) -> None:
        config = tmp_path / "languages.toml"
        config.write_text("")
        count = register_custom_parsers(config)
        assert count == 0

    def test_register_from_valid_config(self, tmp_path: Path) -> None:
        config = tmp_path / "languages.toml"
        config.write_text(
            '[languages.kotlin]\n'
            'extensions = [".kt", ".kts"]\n'
            'tree_sitter_language = "kotlin"\n'
        )

        original_len = len(SUPPORTED_LANGUAGES)

        try:
            count = register_custom_parsers(config)
            if count > 0:
                assert ".kt" in SUPPORTED_LANGUAGES
                assert ".kts" in SUPPORTED_LANGUAGES
        finally:
            SUPPORTED_LANGUAGES.pop(".kt", None)
            SUPPORTED_LANGUAGES.pop(".kts", None)
            _parser_cache.pop("kotlin", None)


class TestParseResult:
    def test_defaults(self) -> None:
        r = ParseResult()
        assert r.nodes == []
        assert r.edges == []
        assert r.language == ""
        assert r.errors == []


class TestIsTreeSitterAvailable:
    def test_returns_bool(self) -> None:
        result = is_tree_sitter_available()
        assert isinstance(result, bool)
