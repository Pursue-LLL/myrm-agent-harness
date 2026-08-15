"""Tests for MCP stdio runtime parameter resolution (placeholders.py)."""

from __future__ import annotations

from myrm_agent_harness.toolkits.mcp.placeholders import (
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
