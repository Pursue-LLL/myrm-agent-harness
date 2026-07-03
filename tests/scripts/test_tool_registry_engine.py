"""Unit tests for scripts.tool_registry_engine.

Exercises the AST scanners against synthetic source trees produced under
`tmp_path` so the tests stay fast (~0.1s each) and hermetic — they neither
import the harness package nor depend on real `_TOOL_LAYERS` contents.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.tool_registry_engine import (
    _build_string_constants,
    _collect_basetool_subclass,
    _collect_decorated_tools,
    _collect_factories,
    _collect_middleware_renames,
    _collect_module_tool_assignments,
    _count_call_sites,
    _decorator_is_tool,
    _iter_python_files,
    _parse,
    _resolve_layer_literal,
    _tool_name_from_decorator,
    get_changed_python_files,
)


def _tree(src: str) -> ast.Module:
    return ast.parse(src)


def test_decorator_is_tool_matches_bare_and_call_form() -> None:
    src = """
@tool
def a(): pass

@tool("x")
def b(): pass

@something_else
def c(): pass
"""
    tree = _tree(src)
    decorators = [
        n.decorator_list[0]
        for n in tree.body
        if isinstance(n, ast.FunctionDef)
    ]
    assert _decorator_is_tool(decorators[0]) is True
    assert _decorator_is_tool(decorators[1]) is True
    assert _decorator_is_tool(decorators[2]) is False


def test_decorator_is_tool_rejects_attribute_form() -> None:
    """`@x.tool` is NOT the same as `@tool` — guard against false positives."""
    src = "@x.tool\ndef a(): pass\n"
    decorator = _tree(src).body[0].decorator_list[0]  # type: ignore[attr-defined]
    assert _decorator_is_tool(decorator) is False


def test_build_string_constants_handles_assign_and_annassign() -> None:
    src = """
TOOL_NAME = "alpha"
OTHER: str = "beta"
_NOT_STR = 42
"""
    constants = _build_string_constants(_tree(src))
    assert constants["TOOL_NAME"] == "alpha"
    assert constants["OTHER"] == "beta"
    assert "_NOT_STR" not in constants


def test_tool_name_resolves_literal_local_and_cross_module_constants() -> None:
    src = """
LOCAL = "local_name"

@tool(LOCAL)
def a(): pass

@tool("literal_name")
def b(): pass

@tool(CONVERSATION_SEARCH_TOOL_NAME)
def c(): pass

@tool
def fallback(): pass
"""
    tree = _tree(src)
    constants = _build_string_constants(tree)
    decorators = {
        n.name: n.decorator_list[0]
        for n in tree.body
        if isinstance(n, ast.FunctionDef)
    }
    assert _tool_name_from_decorator(decorators["a"], "a", constants) == "local_name"
    assert _tool_name_from_decorator(decorators["b"], "b", constants) == "literal_name"
    assert _tool_name_from_decorator(decorators["c"], "c", constants) == "conversation_search_tool"
    assert _tool_name_from_decorator(decorators["fallback"], "fallback", constants) == "fallback"


def test_tool_name_falls_back_to_func_name_for_unknown_constant() -> None:
    src = "@tool(MYSTERY)\ndef foo(): pass\n"
    tree = _tree(src)
    decorator = tree.body[0].decorator_list[0]  # type: ignore[attr-defined]
    assert _tool_name_from_decorator(decorator, "foo", {}) == "foo"


def test_collect_decorated_tools_catches_nested_functions() -> None:
    """Factory closures hide `@tool` inside `def create_*():` — must be caught."""
    src = """
def create_some_tools():
    @tool("nested_tool")
    def inner(): pass
    return [inner]

@tool("top_level_tool")
def top(): pass
"""
    decls = _collect_decorated_tools(_tree(src), Path("/x.py"))
    names = {d.name for d in decls}
    assert names == {"nested_tool", "top_level_tool"}


def test_collect_basetool_subclass_recognises_both_assign_styles() -> None:
    src_annassign = "class MyTool(BaseTool):\n    name: str = \"ann_tool\"\n"
    src_plain = "class MyTool(BaseTool):\n    name = \"plain_tool\"\n"
    src_not_basetool = "class Other(BaseClass):\n    name = \"ignored\"\n"

    for src, expected in [(src_annassign, "ann_tool"), (src_plain, "plain_tool")]:
        node = _tree(src).body[0]
        assert isinstance(node, ast.ClassDef)
        decls = _collect_basetool_subclass(node, Path("/x.py"))
        assert len(decls) == 1
        assert decls[0].name == expected
        assert decls[0].container == "MyTool"
        assert decls[0].kind == "basetool"

    node = _tree(src_not_basetool).body[0]
    assert isinstance(node, ast.ClassDef)
    assert _collect_basetool_subclass(node, Path("/x.py")) == []


def test_collect_middleware_renames_picks_up_attribute_assignment() -> None:
    src = """
glob_tool.name = "glob_search"
some_other = "ignored"
"""
    decls = _collect_middleware_renames(_tree(src), Path("/m.py"))
    names = {d.name for d in decls}
    assert names == {"glob_search"}


def test_collect_module_tool_assignments_handles_double_call_form() -> None:
    """`xxx = tool("name")(func)` is a real LangChain construction pattern."""
    src = """
LOCAL = "via_const"
my_tool = tool("via_literal")(some_func)
const_tool = tool(LOCAL)(another_func)
non_tool = something_else()(x)
"""
    tree = _tree(src)
    constants = _build_string_constants(tree)
    decls = _collect_module_tool_assignments(tree, Path("/x.py"), constants)
    names = {d.name for d in decls}
    assert names == {"via_literal", "via_const"}


def test_collect_factories_picks_create_underscore_tool_naming() -> None:
    src = """
def create_browser_tools(): ...
def create_skill_select_tool(): ...
async def create_async_tools(): ...
def helper(): ...
def setup_tools(): ...
"""
    factories = _collect_factories(_tree(src), Path("/f.py"))
    assert set(factories) == {"create_browser_tools", "create_skill_select_tool", "create_async_tools"}


def test_count_call_sites_excludes_definition_only_files(tmp_path: Path) -> None:
    """A file that only declares `def foo(...)` but never calls `foo(...)` is not a caller."""
    def_only = tmp_path / "def_only.py"
    def_only.write_text("def create_demo_tool():\n    return None\n")

    caller = tmp_path / "caller.py"
    caller.write_text("from x import create_demo_tool\ncreate_demo_tool()\n")

    sites = _count_call_sites({"create_demo_tool"}, (tmp_path,))
    assert def_only not in sites["create_demo_tool"]
    assert caller in sites["create_demo_tool"]


def test_iter_python_files_excludes_test_and_cache_dirs(tmp_path: Path) -> None:
    (tmp_path / "real.py").write_text("x = 1\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "compiled.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text("x = 1\n")
    (tmp_path / "missing_dir")

    files = _iter_python_files(tmp_path)
    file_names = {f.name for f in files}
    assert file_names == {"real.py"}


def test_iter_python_files_returns_empty_for_missing_root(tmp_path: Path) -> None:
    assert _iter_python_files(tmp_path / "does_not_exist") == []


def test_parse_returns_none_on_syntax_error_and_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n    pass\n")
    assert _parse(bad) is None
    captured = capsys.readouterr()
    assert "syntax error" in captured.err


def test_parse_returns_none_on_unicode_decode_error(tmp_path: Path) -> None:
    bad = tmp_path / "binary.py"
    bad.write_bytes(b"\xff\xfe\x00\x00not utf-8")
    assert _parse(bad) is None


def test_resolve_layer_literal_attribute_form() -> None:
    """`ToolLayer.CORE` → "CORE"; other forms → None."""
    tree = _tree("x = ToolLayer.CORE\ny = SomeOther.CORE\n")
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)]
    assert _resolve_layer_literal(assignments[0].value) == "CORE"
    assert _resolve_layer_literal(assignments[1].value) is None


def test_get_changed_python_files_returns_none_if_git_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive path: when `git` isn't on PATH, callers must get None."""
    import subprocess as _sp

    def _fake_run(*_a: object, **_kw: object) -> _sp.CompletedProcess[str]:
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(_sp, "run", _fake_run)
    assert get_changed_python_files((Path("/tmp/never"),)) is None
