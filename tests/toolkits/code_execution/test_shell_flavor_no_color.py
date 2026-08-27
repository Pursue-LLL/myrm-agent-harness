"""Tests for BashFlavor init commands: NO_COLOR / FORCE_COLOR / TERM settings."""

from __future__ import annotations

import subprocess

import pytest

from myrm_agent_harness.toolkits.code_execution.session.shell_flavor import BashFlavor


def _bash_roundtrip(value: str) -> str:
    """Inject ``value`` via format_env_set, then read it back with printf.

    Reads raw bytes so literal ``\\r`` survives (text mode would translate it
    through universal newlines).
    """
    cmd = BashFlavor().format_env_set("MY_KEY", value) + "; printf '%s' \"$MY_KEY\""
    proc = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, f"bash rejected injected env: {proc.stderr!r}"
    return proc.stdout.decode("utf-8")


class TestBashFlavorEnvQuoting:
    """format_env_set must survive arbitrary env values byte-for-byte.

    Env values travel through a long-lived interactive bash, so ``$``/backticks
    must not be re-expanded and a single literal ``"`` must not close the
    quoting early (which previously wedged the shell in PS2 continuation).
    """

    @pytest.mark.parametrize(
        "value",
        [
            "plain",
            "",
            "with spaces",
            'with "double" quotes',
            'a"b',  # odd quote count: previously hung the shell
            "it's single quotes",
            r"back\\slash",
            r"path\/to\/file",
            "$HOME",  # must NOT expand
            "`whoami`",  # must NOT execute
            r"\$NOT_VAR",  # literal dollar
            "!history",
            "%percent%",
            "100%",
            "mixed \"quotes\" and $VAR and `cmd` and 'sq'",
            "tab\there",
            "newline\nhere",
            "cr\rhere",
            "中文值 and émojis 🚀",
            "comma, semicolon; pipe| redirect> < and&",
        ],
    )
    def test_env_value_roundtrip_literal(self, value: str) -> None:
        assert _bash_roundtrip(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            'a"b',
            "line1\nline2",
            "$HOME",
            "it's",
        ],
    )
    def test_env_command_stays_single_line(self, value: str) -> None:
        """The generated export command must never split across batch lines."""
        cmd = BashFlavor().format_env_set("KEY", value)
        assert "\n" not in cmd
        assert cmd.startswith("export KEY=$'")
        assert cmd.endswith("'")

    def test_multiple_env_values_inject_cleanly(self) -> None:
        flavor = BashFlavor()
        cmds = [
            flavor.format_env_set("K1", 'a"b'),
            flavor.format_env_set("K2", "$HOME"),
            flavor.format_env_set("K3", "plain"),
        ]
        joined = "\n".join(cmds) + '\nprintf \'%s|%s|%s\' "$K1" "$K2" "$K3"'
        proc = subprocess.run(["bash", "-c", joined], capture_output=True, text=True, check=False)
        assert proc.returncode == 0
        assert proc.stdout == 'a"b|$HOME|plain'


class TestBashFlavorNoColor:
    """Verify BashFlavor.build_init_commands sets NO_COLOR environment."""

    def test_init_commands_contain_no_color(self) -> None:
        flavor = BashFlavor()
        cmds = flavor.build_init_commands("/workspace", timeout=60, max_memory_mb=2048)

        export_cmd = next(c for c in cmds if c.startswith("export"))
        assert "NO_COLOR=1" in export_cmd
        assert "FORCE_COLOR=0" in export_cmd
        assert "TERM=dumb" in export_cmd

    def test_ps1_ps2_still_set(self) -> None:
        flavor = BashFlavor()
        cmds = flavor.build_init_commands("/workspace", timeout=60, max_memory_mb=2048)

        export_cmd = next(c for c in cmds if c.startswith("export"))
        assert "PS1=''" in export_cmd
        assert "PS2=''" in export_cmd

    def test_single_export_line(self) -> None:
        """All env vars in one export line for minimal shell round-trips."""
        flavor = BashFlavor()
        cmds = flavor.build_init_commands("/workspace", timeout=60, max_memory_mb=2048)

        export_lines = [c for c in cmds if c.startswith("export")]
        assert len(export_lines) == 1

    def test_exit_interceptor_injected(self) -> None:
        """Init commands contain the exit() interceptor so the persistent shell
        survives trailing ``exit`` in LLM-generated commands."""
        flavor = BashFlavor()
        cmds = flavor.build_init_commands("/workspace", timeout=60, max_memory_mb=2048)

        exit_lines = [c for c in cmds if c.startswith("exit()")]
        assert len(exit_lines) == 1
        assert "builtin return" in exit_lines[0]

    def test_wrapped_command_multiline_rc_capture(self) -> None:
        """The wrapper captures rc inside the block so comment-only or empty
        commands cannot wedge an open brace block (which would hang the shell),
        and an EXIT trap backs up the marker pair for errexit crashes."""
        flavor = BashFlavor()
        wrapped = flavor.build_wrapped_command("echo hi", "EX", "END", "$?")

        assert wrapped.startswith('trap \'echo "EX"$?; echo "END"\' EXIT\n{\necho hi\n')
        assert "__myrm_rc__=$?" in wrapped
        assert "}\necho 'EX'" in wrapped
        assert "\necho 'END'\n" in wrapped

    def test_wrapped_command_single_line_variant(self) -> None:
        """A single-line command still round-trips through the wrapper."""
        flavor = BashFlavor()
        wrapped = flavor.build_wrapped_command("echo a; echo b", "EX", "END", "$?")
        assert "{\necho a; echo b\n__myrm_rc__=$?\n}\n" in wrapped


class TestPowerShellFlavor:
    """Tests for PowerShellFlavor init commands, env setting, and command wrapping."""

    def test_init_commands_contain_utf8_and_progress_preference(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.session.shell_flavor import (
            PowerShellFlavor,
        )

        flavor = PowerShellFlavor()
        cmds = flavor.build_init_commands("C:\\workspace", timeout=60, max_memory_mb=2048)

        joined = "\n".join(cmds)
        assert "OutputEncoding = [System.Text.Encoding]::UTF8" in joined
        assert "$ProgressPreference = 'SilentlyContinue'" in joined
        assert "$ErrorActionPreference = 'Continue'" in joined
        assert "function prompt { '' }" in joined
        assert "function exit" in joined
        assert "Set-Location -LiteralPath 'C:\\workspace'" in joined

    def test_format_env_set(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.session.shell_flavor import (
            PowerShellFlavor,
        )

        flavor = PowerShellFlavor()
        cmd = flavor.format_env_set("MY_KEY", "value with 'quote' & $special")
        assert cmd == "$env:MY_KEY = 'value with ''quote'' & $special'"

    def test_build_wrapped_command(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.session.shell_flavor import (
            PowerShellFlavor,
        )

        flavor = PowerShellFlavor()
        wrapped = flavor.build_wrapped_command("Get-ChildItem", "EXIT_MARK", "END_MARK", "$__myrm_rc__")

        assert "& {" in wrapped
        assert "Get-ChildItem" in wrapped
        assert "$LASTEXITCODE" in wrapped
        assert "Write-Output 'EXIT_MARK'$__myrm_rc__" in wrapped
        assert "Write-Output 'END_MARK'" in wrapped

    def test_get_flavor_returns_powershell_when_configured(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.platform import PlatformInfo
        from myrm_agent_harness.toolkits.code_execution.session.shell_flavor import (
            PowerShellFlavor,
            WindowsFlavor,
            get_flavor,
        )

        pwsh_platform = PlatformInfo(
            os_type="windows",
            os_release="10.0",
            arch="AMD64",
            is_wsl=False,
            shell_path="powershell.exe",
            shell_args=("-NoLogo", "-NoProfile"),
            shell_type="powershell",
            exit_code_var="$__myrm_rc__",
            env_set_template="$env:{key}={value}",
            path_separator=";",
            process_group_creation_flag=0x00000200,
            safe_env_vars=frozenset(),
        )
        assert isinstance(get_flavor(pwsh_platform), PowerShellFlavor)

        cmd_platform = PlatformInfo(
            os_type="windows",
            os_release="10.0",
            arch="AMD64",
            is_wsl=False,
            shell_path="cmd.exe",
            shell_args=("/Q",),
            shell_type="cmd",
            exit_code_var="%ERRORLEVEL%",
            env_set_template="set {key}={value}",
            path_separator=";",
            process_group_creation_flag=0x00000200,
            safe_env_vars=frozenset(),
        )
        assert isinstance(get_flavor(cmd_platform), WindowsFlavor)

