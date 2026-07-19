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
