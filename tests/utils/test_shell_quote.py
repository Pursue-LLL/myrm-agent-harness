"""Unit tests for universal cross-platform shell argument quoting."""

from __future__ import annotations

import pytest

from myrm_agent_harness.utils.shell_quote import (
    posix_shell_quote,
    shell_quote,
    windows_cmd_quote,
    windows_powershell_quote,
)


def test_posix_shell_quote() -> None:
    # Empty string
    assert posix_shell_quote("") == "''"
    # Safe path
    assert posix_shell_quote("src/app/main.py") == "src/app/main.py"
    # Spaces and special characters
    assert posix_shell_quote("hello world") == "'hello world'"
    assert posix_shell_quote("foo'bar") == "'foo'\"'\"'bar'"
    assert posix_shell_quote("user; rm -rf /") == "'user; rm -rf /'"


def test_windows_cmd_quote_safe_and_empty() -> None:
    # Empty string
    assert windows_cmd_quote("") == '""'
    # Safe path/characters pass-through
    assert windows_cmd_quote(r"C:\Users\test\file.txt") == r"C:\Users\test\file.txt"
    assert windows_cmd_quote("normal_word123") == "normal_word123"


def test_windows_cmd_quote_spaces_and_quotes() -> None:
    # Spaces require quotes
    assert windows_cmd_quote(r"C:\Program Files\App\bin.exe") == r'"C:\Program Files\App\bin.exe"'
    # Embedded double quotes
    assert windows_cmd_quote('hello "world"') == r'"hello \"world\""'
    # Trailing backslash before double quote
    assert windows_cmd_quote(r'C:\foo\bar\"') == r'"C:\foo\bar\\\""'
    # Trailing backslashes before closing quote when force_quote=True
    assert windows_cmd_quote(r"C:\foo\bar\\", force_quote=True) == r'"C:\foo\bar\\\\"'


def test_windows_cmd_quote_metacharacters() -> None:
    # CMD metacharacters escaping when flag is enabled
    quoted_amp = windows_cmd_quote("foo & dir", escape_cmd_metachars=True)
    assert "^&" in quoted_amp
    # Environment variable reference
    quoted_env = windows_cmd_quote("%PATH%", escape_cmd_metachars=True)
    assert "^%" in quoted_env


def test_windows_powershell_quote() -> None:
    # Empty string
    assert windows_powershell_quote("") == "''"
    # Safe string
    assert windows_powershell_quote("simple") == "simple"
    # String with spaces and single quotes
    assert windows_powershell_quote("hello world") == "'hello world'"
    assert windows_powershell_quote("don't stop") == "'don''t stop'"
    assert windows_powershell_quote("$variable") == "'$variable'"


def test_windows_cmd_quote_multiline_sanitization() -> None:
    # Multiline string with CRLF, CR, LF
    raw = "echo line1\r\necho line2\nline3\rline4"
    quoted = windows_cmd_quote(raw)
    assert "\r" not in quoted
    assert "\n" not in quoted
    assert "echo line1 echo line2 line3 line4" in quoted


def test_shell_quote_facade() -> None:
    assert shell_quote("hello world", platform="posix") == "'hello world'"
    assert shell_quote(r"C:\Program Files\App", platform="windows") == r'"C:\Program Files\App"'
    assert shell_quote("$env:VAR", platform="powershell") == "'$env:VAR'"


def test_shell_quote_auto_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    assert shell_quote("hello world") == "'hello world'"

    monkeypatch.setattr("sys.platform", "win32")
    assert shell_quote("hello world") == '"hello world"'

