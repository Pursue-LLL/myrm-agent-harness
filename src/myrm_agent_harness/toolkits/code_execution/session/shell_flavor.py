"""Platform-specific shell behavior drivers.

[INPUT]
platform::PlatformInfo (POS: OS detection and shell path resolution)

[OUTPUT]
ShellFlavor: ABC for platform-specific shell command formatting.
BashFlavor: Bash/POSIX shell driver with ulimit init.
WindowsFlavor: Windows cmd driver.
get_flavor: Factory returning the appropriate flavor for the platform.

[POS]
Platform-specific shell command formatting. Encapsulates differences between
Bash and Windows cmd for command wrapping, env injection, and init sequences.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.platform import PlatformInfo


class ShellFlavor(ABC):
    """Platform-specific shell behavior driver."""

    @abstractmethod
    def build_init_commands(
        self, work_dir: str, timeout: int, max_memory_mb: int
    ) -> list[str]: ...

    @abstractmethod
    def format_env_set(self, key: str, value: str) -> str: ...

    @abstractmethod
    def build_wrapped_command(
        self, command: str, exit_marker: str, end_marker: str, exit_code_var: str
    ) -> str: ...


class BashFlavor(ShellFlavor):
    def build_init_commands(
        self, work_dir: str, timeout: int, max_memory_mb: int
    ) -> list[str]:
        memory_kb = max_memory_mb * 1024
        cpu_limit = max(600, timeout * 5)

        # On macOS, ulimit -v can cause simple forks to fail due to large
        # shared system cache VM sizes. Also ulimit -u on macOS applies per
        # user, so 512 is too low for a developer machine.
        if sys.platform == "darwin":
            ulimit_cmd = f"ulimit -t {cpu_limit} 2>/dev/null || true"
        else:
            ulimit_cmd = (
                f"ulimit -t {cpu_limit} -v {memory_kb} -u 512 2>/dev/null || true"
            )

        return [
            "set +o history 2>/dev/null || true",
            "export PS1='' PS2=''",
            f"cd '{work_dir}' || cd /tmp",
            ulimit_cmd,
        ]

    def format_env_set(self, key: str, value: str) -> str:
        escaped = value.replace("\\\\", "\\\\\\\\").replace('"', '\\\\"')
        return f'export {key}="{escaped}"'

    def build_wrapped_command(
        self, command: str, exit_marker: str, end_marker: str, exit_code_var: str
    ) -> str:
        return (
            f"{{ {command}; }}\n"
            f"__myrm_rc__={exit_code_var}\n"
            f"echo '{exit_marker}'\"$__myrm_rc__\"\n"
            f"echo '{end_marker}'\n"
        )


class WindowsFlavor(ShellFlavor):
    def build_init_commands(
        self, work_dir: str, timeout: int, max_memory_mb: int
    ) -> list[str]:
        return ["@echo off", "prompt $G", f'cd /d "{work_dir}"']

    def format_env_set(self, key: str, value: str) -> str:
        return f"set {key}={value.replace('%', '%%')}"

    def build_wrapped_command(
        self, command: str, exit_marker: str, end_marker: str, exit_code_var: str
    ) -> str:
        return (
            f"{command}\r\necho {exit_marker}{exit_code_var}\r\necho {end_marker}\r\n"
        )


def get_flavor(platform_info: PlatformInfo) -> ShellFlavor:
    """Factory: return the appropriate shell flavor for the detected platform."""
    return WindowsFlavor() if platform_info.is_windows else BashFlavor()
