"""Tests for BashFlavor init commands: NO_COLOR / FORCE_COLOR / TERM settings."""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.session.shell_flavor import BashFlavor


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

        assert wrapped.startswith("trap 'echo \"EX\"$?; echo \"END\"' EXIT\n{\necho hi\n")
        assert "__myrm_rc__=$?" in wrapped
        assert "}\necho 'EX'" in wrapped
        assert "\necho 'END'\n" in wrapped

    def test_wrapped_command_single_line_variant(self) -> None:
        """A single-line command still round-trips through the wrapper."""
        flavor = BashFlavor()
        wrapped = flavor.build_wrapped_command("echo a; echo b", "EX", "END", "$?")
        assert "{\necho a; echo b\n__myrm_rc__=$?\n}\n" in wrapped
