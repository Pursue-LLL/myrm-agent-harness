import builtins
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator import DeltaSyntaxValidator


def test_python_valid_syntax():
    post_content = "def hello():\n    print('world')\n"
    # Should not raise exception
    DeltaSyntaxValidator.validate("test.py", post_content, pre_content=None)

def test_python_invalid_syntax_no_pre_content():
    post_content = "def hello()\n    print('world')\n"
    with pytest.raises(ValueError, match="Syntax validation failed"):
        DeltaSyntaxValidator.validate("test.py", post_content, pre_content=None)

def test_python_new_error_with_clean_pre_content():
    pre_content = "def hello():\n    print('world')\n"
    post_content = "def hello()\n    print('world')\n"
    with pytest.raises(ValueError, match="New syntax errors introduced"):
        DeltaSyntaxValidator.validate("test.py", post_content, pre_content=pre_content)

def test_python_same_error_is_ignored():
    pre_content = "def hello()\n    print('world')\n"
    post_content = "def hello()\n    print('world2')\n"
    # Both have the same SyntaxError at the same location
    # Should not raise exception
    DeltaSyntaxValidator.validate("test.py", post_content, pre_content=pre_content)

def test_python_new_error_with_broken_pre_content():
    pre_content = "def hello()\n    print('world')\n"
    # Fixed the previous error, but introduced a new one (IndentationError)
    post_content = "def hello():\nprint('world')\n"
    with pytest.raises(ValueError, match="New syntax errors introduced"):
        DeltaSyntaxValidator.validate("test.py", post_content, pre_content=pre_content)

def test_json_valid():
    post_content = '{"key": "value"}'
    DeltaSyntaxValidator.validate("test.json", post_content, pre_content=None)

def test_json_invalid_trailing_comma():
    pre_content = '{"key": "value"}'
    post_content = '{"key": "value",}'
    with pytest.raises(ValueError, match="New syntax errors introduced"):
        DeltaSyntaxValidator.validate("test.json", post_content, pre_content=pre_content)

def test_unknown_extension():
    post_content = "some arbitrary content\n  with invalid syntax { } ["
    # No linter for .txt, should pass
    DeltaSyntaxValidator.validate("test.txt", post_content, pre_content=None)

def test_python_shifted_error_is_ignored():
    # Pre-content has error at line 1
    pre_content = "def hello()\n    print('world')\n"
    # Post-content adds a newline at the top, shifting the error to line 2
    post_content = "\ndef hello()\n    print('world')\n"

    # Due to line shifting, line 1 error becomes line 2 error.
    # Without _strip_line_col, this would raise a ValueError.
    # With _strip_line_col, the error signature matches and is ignored.
    DeltaSyntaxValidator.validate("test.py", post_content, pre_content=pre_content)

def test_json_shifted_error_is_ignored():
    pre_content = '{\n"key": "value",\n}'
    post_content = '\n{\n"key": "value",\n}'
    DeltaSyntaxValidator.validate("test.json", post_content, pre_content=pre_content)

def test_yaml_valid():
    post_content = "key: value\nlist:\n  - item1\n"
    DeltaSyntaxValidator.validate("test.yaml", post_content, pre_content=None)

def test_yaml_invalid():
    pre_content = "key: value\n"
    post_content = "key: value\nlist: [unclosed\n"
    with pytest.raises(ValueError, match="New syntax errors introduced"):
        DeltaSyntaxValidator.validate("test.yaml", post_content, pre_content=pre_content)

def test_yaml_shifted_error_is_ignored():
    pre_content = "list: [unclosed\n"
    post_content = "\nlist: [unclosed\n"
    DeltaSyntaxValidator.validate("test.yml", post_content, pre_content=pre_content)

def test_toml_valid():
    post_content = '[table]\nkey = "value"\n'
    DeltaSyntaxValidator.validate("test.toml", post_content, pre_content=None)

def test_toml_invalid():
    pre_content = '[table]\nkey = "value"\n'
    post_content = '[table\nkey = "value"\n'
    with pytest.raises(ValueError, match="New syntax errors introduced"):
        DeltaSyntaxValidator.validate("test.toml", post_content, pre_content=pre_content)

def test_toml_shifted_error_is_ignored():
    pre_content = '[table\nkey = "value"\n'
    post_content = '\n[table\nkey = "value"\n'
    DeltaSyntaxValidator.validate("test.toml", post_content, pre_content=pre_content)


def test_json_linter_generic_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator as mod

    def _boom(_content: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(mod.json, "loads", _boom)
    ok, err = mod._lint_json_inproc("{}")
    assert ok is False
    assert "RuntimeError" in err


def test_yaml_linter_skips_when_yaml_missing() -> None:
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_arg: dict[str, object] | None = None,
        locals_arg: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "yaml":
            raise ImportError()
        return real_import(name, globals_arg, locals_arg, fromlist, level)

    import myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator as mod

    with patch("builtins.__import__", side_effect=fake_import):
        ok, msg = mod._lint_yaml_inproc("key: x")
    assert ok is True
    assert msg == "__SKIP__"


def test_yaml_linter_generic_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import yaml  # type: ignore[import-untyped]

    import myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator as mod

    def _boom(_content: str) -> None:
        raise ValueError("bad yaml")

    monkeypatch.setattr(yaml, "safe_load", _boom)
    ok, err = mod._lint_yaml_inproc("key: value\n")
    assert ok is False
    assert "ValueError" in err


def test_toml_linter_skips_when_no_parser() -> None:
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_arg: dict[str, object] | None = None,
        locals_arg: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name in ("tomllib", "tomli"):
            raise ImportError()
        return real_import(name, globals_arg, locals_arg, fromlist, level)

    import myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator as mod

    with patch("builtins.__import__", side_effect=fake_import):
        ok, msg = mod._lint_toml_inproc("a = 1")
    assert ok is True
    assert msg == "__SKIP__"


def test_python_linter_generic_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import myrm_agent_harness.agent.meta_tools.file_ops.validators.delta_syntax_validator as mod

    def _boom(_source: str, _filename: str = "<unknown>", _mode: str = "exec") -> None:
        raise MemoryError("simulated")

    monkeypatch.setattr(mod.ast, "parse", _boom)
    ok, err = mod._lint_python_inproc("x = 1\n")
    assert ok is False
    assert "MemoryError" in err

