"""Tests for MCP stdio runtime parameter resolution (placeholders.py)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.mcp import placeholders
from myrm_agent_harness.toolkits.mcp.placeholders import (
    apply_windows_script_interpreter,
    expand_placeholders,
    resolve_stdio_launch,
)

_ROOT = "/data/plugins/demo-plugin"
_DATA = "/data/plugins/demo-plugin_data"


class TestExpandPlaceholders:
    def test_fast_path_without_placeholder(self) -> None:
        assert expand_placeholders("plain/value") == "plain/value"

    def test_expands_both_whitelisted(self) -> None:
        value = "${PLUGIN_ROOT}/bin/pdf --data ${PLUGIN_DATA}/cache"
        assert (
            expand_placeholders(value, plugin_root=_ROOT, data_root=_DATA)
            == f"{_ROOT}/bin/pdf --data {_DATA}/cache"
        )

    def test_unknown_placeholder_preserved(self) -> None:
        assert (
            expand_placeholders("${OTHER_VAR}/x", plugin_root=_ROOT, data_root=_DATA)
            == "${OTHER_VAR}/x"
        )

    def test_missing_root_leaves_placeholder(self) -> None:
        assert expand_placeholders("${PLUGIN_ROOT}/bin") == "${PLUGIN_ROOT}/bin"

    def test_single_pass_non_recursive(self) -> None:
        # A substituted root value must never be re-expanded (single textual pass).
        nested_root = "${PLUGIN_ROOT}"
        assert (
            expand_placeholders("${PLUGIN_ROOT}", plugin_root=nested_root)
            == "${PLUGIN_ROOT}"
        )


class TestResolveStdioLaunch:
    def test_empty_extra_params_returns_blanks(self) -> None:
        command, args, env, cwd = resolve_stdio_launch("bin/srv", ["--x"], None)
        assert command == "bin/srv"
        assert args == ["--x"]
        assert env is None
        assert cwd is None

    def test_env_reads_from_extra_params_and_filters_empty(self) -> None:
        _, _, env, _ = resolve_stdio_launch(
            "python",
            None,
            {"env": {"API_KEY": "abc", "EMPTY": "", "NONE": None}},
        )
        assert env == {"API_KEY": "abc"}
        assert "EMPTY" not in env and "NONE" not in env

    def test_env_expands_placeholders_and_injects_reserved(self) -> None:
        _, _, env, _ = resolve_stdio_launch(
            "python",
            None,
            {
                "env": {"ROOT": "${PLUGIN_ROOT}/x", "DATA": "${PLUGIN_DATA}"},
                "plugin_root": _ROOT,
                "data_root": _DATA,
            },
        )
        assert env == {
            "ROOT": f"{_ROOT}/x",
            "DATA": _DATA,
            "PLUGIN_ROOT": _ROOT,
            "PLUGIN_DATA": _DATA,
        }

    def test_injects_reserved_env_without_declared_env(self) -> None:
        _, _, env, _ = resolve_stdio_launch(
            "./bin/srv",
            None,
            {"plugin_root": _ROOT, "data_root": _DATA},
        )
        assert env == {"PLUGIN_ROOT": _ROOT, "PLUGIN_DATA": _DATA}

    def test_injects_only_configured_roots(self) -> None:
        _, _, env, _ = resolve_stdio_launch(
            "./bin/srv",
            None,
            {"plugin_root": _ROOT},
        )
        assert env == {"PLUGIN_ROOT": _ROOT}
        assert "PLUGIN_DATA" not in env

    def test_injects_only_data_root(self) -> None:
        _, _, env, _ = resolve_stdio_launch(
            "./bin/srv",
            None,
            {"data_root": _DATA},
        )
        assert env == {"PLUGIN_DATA": _DATA}
        assert "PLUGIN_ROOT" not in env

    def test_dot_cwd_resolves_to_plugin_root(self) -> None:
        _, _, _, cwd = resolve_stdio_launch(
            "./bin/pdf",
            None,
            {"cwd": "./", "plugin_root": _ROOT, "data_root": _DATA},
        )
        assert cwd == _ROOT

    def test_dot_command_implies_plugin_root_cwd(self) -> None:
        _, _, _, cwd = resolve_stdio_launch(
            "./bin/pdf",
            None,
            {"plugin_root": _ROOT, "data_root": _DATA},
        )
        assert cwd == _ROOT

    def test_relative_cwd_expands_placeholders(self) -> None:
        _, _, _, cwd = resolve_stdio_launch(
            "python",
            None,
            {
                "cwd": "${PLUGIN_DATA}/sub",
                "plugin_root": _ROOT,
                "data_root": _DATA,
            },
        )
        assert cwd == f"{_DATA}/sub"

    def test_args_expand_placeholders_but_not_command(self) -> None:
        command, args, _, _ = resolve_stdio_launch(
            "./bin/srv",
            ["--data", "${PLUGIN_DATA}/cache", "--keep", "${OTHER_VAR}"],
            {"plugin_root": _ROOT, "data_root": _DATA},
        )
        assert command == "./bin/srv"  # command is never expanded (§7.2.1)
        assert args == ["--data", f"{_DATA}/cache", "--keep", "${OTHER_VAR}"]

    def test_no_reserved_injection_without_plugin_roots(self) -> None:
        # Without plugin roots, a plain extra_params dict never injects reserved vars.
        _, _, env, cwd = resolve_stdio_launch("bin/srv", None, {"plugin_name": "demo"})
        assert env is None
        assert cwd is None

    def test_empty_string_roots_treated_as_unconfigured(self) -> None:
        # Empty-string plugin roots must behave like missing roots: no reserved
        # injection and placeholders left intact (matching cwd/env empty-value
        # handling) instead of injecting blank paths or resolving to "/x".
        command, args, env, cwd = resolve_stdio_launch(
            "./bin/srv",
            ["--data", "${PLUGIN_ROOT}/cache"],
            {"plugin_root": "", "data_root": ""},
        )
        assert command == "./bin/srv"
        assert args == ["--data", "${PLUGIN_ROOT}/cache"]
        assert env is None
        assert cwd is None


@pytest.fixture
def windows_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the Windows branch without mutating the real ``os.name``.

    Patching ``os.name`` to ``"nt"`` makes ``pathlib`` instantiate
    ``WindowsPath`` on POSIX (pytest's report/cache paths blow up with
    ``UnsupportedOperation: cannot instantiate 'WindowsPath' on your system``),
    so the module under test exposes its platform probe as a seam instead.
    """
    monkeypatch.setattr(placeholders, "_is_windows", lambda: True)


class TestApplyWindowsScriptInterpreter:
    def test_passthrough_off_windows(self) -> None:
        assert apply_windows_script_interpreter("srv.bat", ["--x"]) == (
            "srv.bat",
            ["--x"],
        )

    def test_passthrough_for_non_script_on_windows(
        self, windows_platform: None
    ) -> None:
        assert apply_windows_script_interpreter("python", ["-m", "srv"]) == (
            "python",
            ["-m", "srv"],
        )

    @pytest.mark.parametrize("script", ["srv.bat", "srv.BAT", "srv.cmd", "C:/t/srv.cmd"])
    def test_batch_mapped_to_cmd(
        self, windows_platform: None, script: str
    ) -> None:
        command, args = apply_windows_script_interpreter(script, ["--x"])
        assert command == "cmd.exe"
        assert args == ["/d", "/c", script, "--x"]

    def test_empty_args(self, windows_platform: None) -> None:
        assert apply_windows_script_interpreter("srv.bat", []) == (
            "cmd.exe",
            ["/d", "/c", "srv.bat"],
        )

    def test_components_with_spaces_or_metachars_are_quoted(
        self, windows_platform: None
    ) -> None:
        command, args = apply_windows_script_interpreter(
            "C:/Program Files/srv.bat", ["a&b", "plain"]
        )
        assert command == "cmd.exe"
        assert args == ["/d", "/c", '"C:/Program Files/srv.bat"', '"a&b"', "plain"]

    def test_embedded_quotes_are_doubled(self, windows_platform: None) -> None:
        _, args = apply_windows_script_interpreter("srv.bat", ['sa"y'])
        assert args == ["/d", "/c", "srv.bat", '"sa""y"']


class TestResolveStdioLaunchWindowsInterpreter:
    """The interpreter wrap must reach *every* consumer of the launch tuple.

    Live spawning reads the tuple the connection manager built, so a wrap that
    only runs inside the transport builder would leave the real spawn path
    unchanged on Windows.
    """

    def test_batch_command_is_wrapped_inside_resolution(self, windows_platform: None) -> None:
        command, args, _, _ = resolve_stdio_launch("srv.bat", ["--x"], None)
        assert command == "cmd.exe"
        assert args == ["/d", "/c", "srv.bat", "--x"]

    def test_wrap_runs_after_placeholder_expansion(self, windows_platform: None) -> None:
        # ``command`` is deliberately never expanded (parser guarantees bare
        # tokens or ``./``-relative paths), so only args carry placeholders.
        command, args, _, _ = resolve_stdio_launch(
            "./bin/srv.cmd",
            ["--data", "${PLUGIN_DATA}/cache"],
            {"plugin_root": _ROOT, "data_root": _DATA},
        )
        assert command == "cmd.exe"
        assert args == ["/d", "/c", "./bin/srv.cmd", "--data", f"{_DATA}/cache"]

    def test_non_script_command_is_untouched(self, windows_platform: None) -> None:
        command, args, _, _ = resolve_stdio_launch("python", ["-m", "srv"], None)
        assert command == "python"
        assert args == ["-m", "srv"]

    def test_off_windows_batch_command_is_untouched(self) -> None:
        command, args, _, _ = resolve_stdio_launch("srv.bat", ["--x"], None)
        assert command == "srv.bat"
        assert args == ["--x"]
