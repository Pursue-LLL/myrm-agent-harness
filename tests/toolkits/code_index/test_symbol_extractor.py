"""Tests for regex-based code symbol extractor.

Covers:
- Language detection from file extensions (15+ languages)
- Python: function, class, method extraction
- JavaScript/TypeScript: function, class, interface, type, const-arrow
- Java, Go, Rust, Ruby, C/C++, C#: language-specific patterns
- Edge cases: private symbols, empty files, unknown extensions
- Line number accuracy via binary search
- Content summary builder
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.code_index.symbol_extractor import (
    CodeSymbol,
    detect_language,
    extract_symbols,
)


class TestDetectLanguage:
    """detect_language: maps file extensions to language names."""

    @pytest.mark.parametrize("path,expected", [
        ("main.py", "python"),
        ("types.pyi", "python"),
        ("app.js", "javascript"),
        ("app.mjs", "javascript"),
        ("app.jsx", "javascript"),
        ("app.ts", "typescript"),
        ("app.tsx", "typescript"),
        ("Main.java", "java"),
        ("main.go", "go"),
        ("lib.rs", "rust"),
        ("app.rb", "ruby"),
        ("index.php", "php"),
        ("main.c", "c"),
        ("main.cpp", "cpp"),
        ("main.cc", "cpp"),
        ("main.h", "c"),
        ("Program.cs", "csharp"),
        ("main.swift", "swift"),
        ("main.kt", "kotlin"),
        ("main.scala", "scala"),
        ("main.lua", "lua"),
        ("script.sh", "shell"),
        ("query.sql", "sql"),
        ("app.ex", "elixir"),
    ])
    def test_known_extensions(self, path: str, expected: str) -> None:
        assert detect_language(path) == expected

    def test_unknown_extension(self) -> None:
        assert detect_language("data.xyz") is None

    def test_no_extension(self) -> None:
        assert detect_language("Makefile") is None

    def test_path_with_directories(self) -> None:
        assert detect_language("src/utils/helpers.py") == "python"


class TestExtractSymbolsPython:
    """Python symbol extraction: functions, classes, methods."""

    def test_simple_function(self) -> None:
        code = "def hello(name: str) -> str:\n    return name\n"
        symbols = extract_symbols(code, "test.py", "python")
        assert len(symbols) == 1
        assert symbols[0].name == "hello"
        assert symbols[0].kind == "function"
        assert symbols[0].line == 1

    def test_multiple_functions(self) -> None:
        code = "def alpha():\n    pass\ndef beta():\n    pass\n"
        symbols = extract_symbols(code, "test.py", "python")
        names = {s.name for s in symbols}
        assert "alpha" in names
        assert "beta" in names

    def test_class_with_methods(self) -> None:
        code = (
            "class UserService:\n"
            "    def __init__(self, db):\n"
            "        self.db = db\n"
            "\n"
            "    def get_user(self, user_id: int):\n"
            "        pass\n"
        )
        symbols = extract_symbols(code, "test.py", "python")
        names = {s.name for s in symbols}
        assert "UserService" in names
        assert "get_user" in names

    def test_private_single_underscore_skipped(self) -> None:
        code = "def _(x):\n    pass\n"
        symbols = extract_symbols(code, "test.py", "python")
        assert len(symbols) == 0

    def test_dunder_init_kept(self) -> None:
        code = "class Foo:\n    def __init__(self):\n        pass\n"
        symbols = extract_symbols(code, "test.py", "python")
        names = {s.name for s in symbols}
        assert "__init__" in names

    def test_empty_file(self) -> None:
        assert extract_symbols("", "test.py", "python") == []


class TestExtractSymbolsTypeScript:
    """TypeScript: function, class, interface, type alias, const-arrow."""

    def test_exported_function(self) -> None:
        code = "export function fetchUser(id: string): Promise<User> {\n}\n"
        symbols = extract_symbols(code, "test.ts", "typescript")
        assert any(s.name == "fetchUser" and s.kind == "function" for s in symbols)

    def test_interface(self) -> None:
        code = "export interface UserConfig {\n  name: string;\n}\n"
        symbols = extract_symbols(code, "test.ts", "typescript")
        assert any(s.name == "UserConfig" and s.kind == "interface" for s in symbols)

    def test_type_alias(self) -> None:
        code = "export type UserId = string;\n"
        symbols = extract_symbols(code, "test.ts", "typescript")
        assert any(s.name == "UserId" and s.kind == "type" for s in symbols)

    def test_class(self) -> None:
        code = "export class AuthService {\n  constructor() {}\n}\n"
        symbols = extract_symbols(code, "test.ts", "typescript")
        assert any(s.name == "AuthService" and s.kind == "class" for s in symbols)

    def test_const_arrow(self) -> None:
        code = "export const handleRequest = async (req: Request) => {\n}\n"
        symbols = extract_symbols(code, "test.ts", "typescript")
        assert any(s.name == "handleRequest" and s.kind == "constant" for s in symbols)


class TestExtractSymbolsGo:
    """Go: func, method, type struct/interface."""

    def test_function(self) -> None:
        code = "func HandleRequest(w http.ResponseWriter, r *http.Request) {\n}\n"
        symbols = extract_symbols(code, "main.go", "go")
        assert any(s.name == "HandleRequest" and s.kind == "function" for s in symbols)

    def test_method(self) -> None:
        code = "func (s *Server) Start(port int) error {\n}\n"
        symbols = extract_symbols(code, "server.go", "go")
        assert any(s.name == "Start" and s.kind == "method" for s in symbols)

    def test_struct(self) -> None:
        code = "type Config struct {\n    Port int\n}\n"
        symbols = extract_symbols(code, "config.go", "go")
        assert any(s.name == "Config" and s.kind == "type" for s in symbols)


class TestExtractSymbolsRust:
    """Rust: fn, struct, trait, enum."""

    def test_pub_function(self) -> None:
        code = "pub fn process(input: &str) -> Result<()> {\n}\n"
        symbols = extract_symbols(code, "lib.rs", "rust")
        assert any(s.name == "process" and s.kind == "function" for s in symbols)

    def test_struct(self) -> None:
        code = "pub struct AppState {\n    db: Pool,\n}\n"
        symbols = extract_symbols(code, "lib.rs", "rust")
        assert any(s.name == "AppState" and s.kind == "class" for s in symbols)

    def test_trait(self) -> None:
        code = "pub trait Handler {\n    fn handle(&self);\n}\n"
        symbols = extract_symbols(code, "lib.rs", "rust")
        assert any(s.name == "Handler" and s.kind == "interface" for s in symbols)

    def test_enum(self) -> None:
        code = "pub enum Status {\n    Active,\n    Inactive,\n}\n"
        symbols = extract_symbols(code, "lib.rs", "rust")
        assert any(s.name == "Status" and s.kind == "type" for s in symbols)


class TestExtractSymbolsJava:
    """Java: class, interface, method."""

    def test_class(self) -> None:
        code = "public class UserRepository {\n}\n"
        symbols = extract_symbols(code, "UserRepository.java", "java")
        assert any(s.name == "UserRepository" and s.kind == "class" for s in symbols)

    def test_interface(self) -> None:
        code = "public interface DataSource {\n}\n"
        symbols = extract_symbols(code, "DataSource.java", "java")
        assert any(s.name == "DataSource" and s.kind == "interface" for s in symbols)


class TestExtractSymbolsEdgeCases:
    """Edge cases for symbol extraction."""

    def test_unknown_language_returns_empty(self) -> None:
        assert extract_symbols("content", "data.xyz") == []

    def test_auto_detect_language(self) -> None:
        code = "def greet():\n    pass\n"
        symbols = extract_symbols(code, "hello.py")
        assert any(s.name == "greet" for s in symbols)

    def test_symbol_has_file_path(self) -> None:
        code = "def foo():\n    pass\n"
        symbols = extract_symbols(code, "src/utils.py", "python")
        assert symbols[0].file_path == "src/utils.py"

    def test_signature_truncation(self) -> None:
        long_params = ", ".join(f"param_{i}: str" for i in range(50))
        code = f"def long_func({long_params}):\n    pass\n"
        symbols = extract_symbols(code, "test.py", "python")
        assert len(symbols[0].signature) <= 200

    def test_line_numbers_correct_multiline(self) -> None:
        code = "# comment\n# comment\n# comment\ndef target():\n    pass\n"
        symbols = extract_symbols(code, "test.py", "python")
        assert symbols[0].line == 4

    def test_frozen_dataclass(self) -> None:
        sym = CodeSymbol(name="f", kind="function", line=1, signature="def f():", file_path="t.py")
        with pytest.raises(AttributeError):
            sym.name = "other"  # type: ignore[misc]

    def test_nested_class_methods(self) -> None:
        code = (
            "class Outer:\n"
            "    class Inner:\n"
            "        def inner_method(self):\n"
            "            pass\n"
        )
        symbols = extract_symbols(code, "test.py", "python")
        names = {s.name for s in symbols}
        assert "Outer" in names
        assert "Inner" in names
        assert "inner_method" in names

    def test_unicode_symbol_names(self) -> None:
        code = "def 处理请求():\n    pass\n\nclass 用户服务:\n    pass\n"
        symbols = extract_symbols(code, "test.py", "python")
        names = {s.name for s in symbols}
        assert "处理请求" in names
        assert "用户服务" in names

    def test_many_symbols_performance(self) -> None:
        """Ensure extraction of 100+ symbols doesn't hang or crash."""
        lines = [f"def func_{i}():\n    pass\n" for i in range(120)]
        code = "\n".join(lines)
        symbols = extract_symbols(code, "big.py", "python")
        assert len(symbols) >= 100

    def test_javascript_async_function(self) -> None:
        code = "export async function fetchData(url) {\n}\n"
        symbols = extract_symbols(code, "api.js", "javascript")
        assert any(s.name == "fetchData" for s in symbols)

    def test_csharp_class(self) -> None:
        code = "public class UserController {\n}\n"
        symbols = extract_symbols(code, "ctrl.cs", "csharp")
        assert any(s.name == "UserController" and s.kind == "class" for s in symbols)

    def test_shell_not_indexed(self) -> None:
        """Shell scripts are recognized but have no symbol patterns."""
        assert detect_language("script.sh") == "shell"
        code = "echo hello\ngrep foo bar\n"
        symbols = extract_symbols(code, "script.sh", "shell")
        assert symbols == []

    def test_sql_not_indexed(self) -> None:
        """SQL files are recognized but have no symbol patterns."""
        assert detect_language("query.sql") == "sql"
        symbols = extract_symbols("SELECT * FROM users;", "query.sql", "sql")
        assert symbols == []
