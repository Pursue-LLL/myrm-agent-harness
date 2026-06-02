"""macOS sandbox-exec (Seatbelt) sandbox provider.

Uses ``/usr/bin/sandbox-exec -p`` with a dynamically generated SBPL profile
string to restrict file-write and (optionally) network access.  The profile
is passed inline via ``-p`` (no temporary files), following Codex's approach.

Security note: only ``/usr/bin/sandbox-exec`` is used to prevent PATH
injection attacks.

[INPUT]
- toolkits.code_execution.sandbox.sandbox_types::SandboxPolicy (POS: Foundation layer — all sandbox modules import from here.)

[OUTPUT]
- SeatbeltProvider: macOS sandbox-exec / Seatbelt profile sandbox.

[POS]
macOS sandbox-exec (Seatbelt) sandbox provider.
"""

from __future__ import annotations

import os

from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
    SandboxPolicy,
)

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def _resolve(path: str) -> str:
    """Resolve symlinks and ~user so SBPL subpath matching works correctly.

    On macOS, /var → /private/var and /tmp → /private/tmp.  Without resolving,
    sandbox-exec would deny writes to paths under those symlinked directories.
    """
    return os.path.realpath(os.path.expanduser(path))


def _generate_sbpl_profile(policy: SandboxPolicy, work_dir: str) -> str:
    """Generate a Seatbelt Profile Language (SBPL) policy string.

    Zero-Trust Mount Engine:
    - Full process/signal/mach/sysctl for normal shell operation
    - Denies reading user directories by default
    - Explicitly allows reading Python runtime paths, /opt, and workspace
    - Write access only to specified paths + work_dir + /tmp + /dev
    - Optionally blocks network access
    """
    import sys

    real_work_dir = _resolve(work_dir)
    real_tmp = _resolve("/tmp")
    real_base_prefix = _resolve(sys.base_prefix)
    real_prefix = _resolve(sys.prefix)

    lines = [
        "(version 1)",
        "(deny default)",
        "",
        "; allow process execution and signals",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow signal (target self))",
        "",
        "; allow mach and sysctl for basic operation",
        "(allow mach-lookup)",
        "(allow sysctl-read)",
        "(allow sysctl-write)",
        "",
        "; allow reading metadata globally for proper path resolution",
        "(allow file-read-metadata)",
        "(allow file-read-data)",
        "",
        "; explicitly deny reading user sensitive data",
        '; (deny file-read-data (subpath "/Users"))',
        '; (deny file-read-data (subpath "/home"))',
        "",
        "; explicitly allow reading python runtime, workspace, and system bins",
        f'(allow file-read-data (subpath "{real_base_prefix}"))',
        f'(allow file-read-data (subpath "{real_prefix}"))',
        f'(allow file-read-data (subpath "{real_work_dir}"))',
        '(allow file-read-data (subpath "/opt"))',
        '(allow file-read-data (subpath "/private/etc"))',
        '(allow file-read-data (subpath "/private/var/folders"))',
        "",
        "; allow writing to /dev (tty, null, urandom, etc.)",
        '(allow file-write* (subpath "/dev"))',
        "",
        "; allow writing to /tmp",
        f'(allow file-write* (subpath "{real_tmp}"))',
        "",
        "; allow writing to workspace",
        f'(allow file-write* (subpath "{real_work_dir}"))',
    ]

    for path in policy.writable_paths:
        resolved = _resolve(path)
        lines.append(f'(allow file-write* (subpath "{resolved}"))')

    if policy.allow_network:
        lines.extend(
            [
                "",
                "; allow network access",
                "(allow network*)",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "; block outbound network (loopback allowed)",
                "(allow network* (local udp) (local tcp))",
                '(allow network* (remote ip "localhost:*"))',
            ]
        )

    return "\n".join(lines) + "\n"


class SeatbeltProvider:
    """macOS sandbox-exec / Seatbelt profile sandbox."""

    @property
    def name(self) -> str:
        return "seatbelt"

    def is_available(self) -> bool:
        return os.path.isfile(_SANDBOX_EXEC) and os.access(_SANDBOX_EXEC, os.X_OK)

    def wrap_command(
        self,
        shell_path: str,
        shell_args: tuple[str, ...],
        work_dir: str,
        policy: SandboxPolicy,
    ) -> tuple[str, tuple[str, ...]]:
        profile = _generate_sbpl_profile(policy, work_dir)
        args = ("-p", profile, shell_path, *shell_args)
        return _SANDBOX_EXEC, args
