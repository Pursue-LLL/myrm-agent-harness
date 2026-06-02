"""Linux bubblewrap (bwrap) sandbox provider.

Creates an isolated mount/PID namespace where the root filesystem is
read-only and only explicitly allowed paths are writable.  Network access
can be restricted by unsharing the network namespace.

Security hardening:
- ``--unshare-pid``: isolate PID namespace so sandboxed processes cannot
  see or signal host processes.
- ``--tmpfs /tmp`` with size cap: prevent disk-fill DoS attacks.
- ``--new-session``: create a new terminal session to block TIOCSTI
  keystroke injection into the parent TTY.

Requires ``bubblewrap`` (``bwrap``) to be installed on the host.

[INPUT]
- toolkits.code_execution.sandbox.sandbox_types::SandboxPolicy (POS: Foundation layer — all sandbox modules import from here.)

[OUTPUT]
- BwrapProvider: Linux bubblewrap namespace sandbox with security hardening.

[POS]
Linux bubblewrap (bwrap) sandbox provider.
"""

from __future__ import annotations

import shutil

from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
    SandboxPolicy,
)

_BWRAP_BIN = "bwrap"
_TMP_SIZE_MB = 512


class BwrapProvider:
    """Linux bubblewrap namespace sandbox with security hardening."""

    @property
    def name(self) -> str:
        return "bwrap"

    def is_available(self) -> bool:
        return shutil.which(_BWRAP_BIN) is not None

    def wrap_command(
        self,
        shell_path: str,
        shell_args: tuple[str, ...],
        work_dir: str,
        policy: SandboxPolicy,
    ) -> tuple[str, tuple[str, ...]]:
        import sys

        args: list[str] = [
            # Zero-Trust Mounts: don't map the entire host /
            "--dir",
            "/",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--ro-bind",
            "/etc/resolv.conf",
            "/etc/resolv.conf",
            "--ro-bind",
            "/etc/ssl/certs",
            "/etc/ssl/certs",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--size",
            str(_TMP_SIZE_MB * 1024 * 1024),
            "--tmpfs",
            "/tmp",
        ]

        # Bind python's own paths so the sandbox can run python
        base_prefix = sys.base_prefix
        prefix = sys.prefix
        seen: set[str] = set(["/", "/bin", "/usr", "/lib", "/lib64", "/etc/resolv.conf", "/etc/ssl/certs", "/dev", "/proc", "/tmp"])

        for path in (base_prefix, prefix):
            if path not in seen:
                seen.add(path)
                args.extend(["--ro-bind", path, path])

        for path in (*policy.writable_paths, work_dir):
            if path not in seen:
                seen.add(path)
                args.extend(["--bind", path, path])

        for path in policy.readable_paths:
            if path not in seen:
                seen.add(path)
                args.extend(["--ro-bind", path, path])

        if not policy.allow_network:
            args.append("--unshare-net")

        args.extend(
            [
                "--unshare-user",
                "--unshare-pid",
                "--new-session",
                "--die-with-parent",
                "--chdir",
                work_dir,
                "--",
                shell_path,
                *shell_args,
            ]
        )

        return _BWRAP_BIN, tuple(args)
