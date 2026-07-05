"""Windows AppContainer sandbox provider.

Uses Windows AppContainer (SID ``S-1-15-2-*``) for native process isolation.
AppContainer restricts filesystem and network access at the OS kernel level,
providing security equivalent to bwrap (Linux) and seatbelt (macOS).

Architecture:
    1. Create (or reuse) an AppContainer profile via ``userenv.dll``.
    2. Set filesystem ACLs via ``icacls.exe`` for allowed paths.
    3. Launch shell with AppContainer security token via
       ``PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES``.

Requirements:
    - Windows 10 1507+ (build 10240).
    - ``icacls.exe`` (ships with all Windows editions).
    - Python ``ctypes`` (Win32 API calls).

[INPUT]
- toolkits.code_execution.sandbox.sandbox_types::SandboxPolicy

[OUTPUT]
- AppContainerProvider: Windows AppContainer native process sandbox.

[POS]
Windows AppContainer (AppContainer) sandbox provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import sys
from typing import Any

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes

from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
    SandboxPolicy,
)

logger = logging.getLogger(__name__)

_PROFILE_PREFIX = "myrm_sandbox_"
_MIN_WIN_BUILD = 10240  # Windows 10 1507


def _get_win_build() -> int:
    """Get the Windows build number."""
    try:
        ver = sys.getwindowsversion()  # type: ignore[attr-defined]
        return ver.build
    except AttributeError:
        return 0


def _compute_policy_fingerprint(policy: SandboxPolicy, work_dir: str) -> str:
    """Deterministic fingerprint for ACL reuse decisions."""
    parts = [
        work_dir,
        str(policy.allow_network),
        *sorted(policy.writable_paths),
        *sorted(policy.readable_paths),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


async def _set_acl(path: str, sid: str, permission: str, *, timeout: int = 30) -> bool:
    """Grant ACL permission to AppContainer SID via icacls."""
    cmd = ["icacls", path, "/grant", f"*{sid}:({permission})", "/T", "/C", "/Q"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            logger.warning(f"icacls failed for {path}: {stderr.decode(errors='replace')}")
            return False
        return True
    except (asyncio.TimeoutError, OSError) as e:
        logger.warning(f"ACL setup failed for {path}: {e}")
        return False


async def _apply_acls(policy: SandboxPolicy, work_dir: str, sid: str) -> bool:
    """Apply filesystem ACLs for the AppContainer profile."""
    tasks: list[asyncio.Task[bool]] = []

    for path in (*policy.writable_paths, work_dir):
        if os.path.exists(path):
            tasks.append(asyncio.create_task(_set_acl(path, sid, "F")))

    for path in policy.readable_paths:
        if os.path.exists(path):
            tasks.append(asyncio.create_task(_set_acl(path, sid, "R")))

    python_paths = {sys.base_prefix, sys.prefix}
    for path in python_paths:
        if os.path.exists(path):
            tasks.append(asyncio.create_task(_set_acl(path, sid, "RX")))

    if not tasks:
        return True

    results = await asyncio.gather(*tasks, return_exceptions=True)
    failures = sum(1 for r in results if r is not True)
    if failures > 0:
        logger.warning(f"ACL setup: {failures}/{len(results)} paths failed")
    return failures == 0


class AppContainerProvider:
    """Windows AppContainer native process sandbox.

    Uses PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES to launch the shell
    process inside an AppContainer, restricting filesystem/network access
    at the kernel level.
    """

    def __init__(self) -> None:
        self._container_name: str | None = None
        self._container_sid: str | None = None
        self._acl_fingerprint: str | None = None
        self._oem_encoding = "utf-8"

    @property
    def name(self) -> str:
        return "appcontainer"

    def is_available(self) -> bool:
        """AppContainer requires Windows 10+ and icacls."""
        if sys.platform != "win32":
            return False
        if _get_win_build() < _MIN_WIN_BUILD:
            return False
        return shutil.which("icacls") is not None

    def wrap_command(
        self,
        shell_path: str,
        shell_args: tuple[str, ...],
        work_dir: str,
        policy: SandboxPolicy,
    ) -> tuple[str, tuple[str, ...]]:
        """Fallback: pass-through (native path via create_process is preferred)."""
        return shell_path, shell_args

    async def create_process(
        self,
        shell_path: str,
        shell_args: tuple[str, ...],
        work_dir: str,
        policy: SandboxPolicy,
        env: dict[str, str],
    ) -> asyncio.subprocess.Process | None:
        """Create process inside AppContainer using Win32 API."""
        if sys.platform != "win32":
            return None

        try:
            await self._ensure_container(policy, work_dir)
        except OSError as e:
            logger.warning(f"AppContainer setup failed, falling back to unsandboxed: {e}")
            return None

        if not self._container_sid:
            return None

        from myrm_agent_harness.toolkits.code_execution.sandbox.providers._win32_defs import (
            get_oem_encoding,
        )

        self._oem_encoding = get_oem_encoding()

        try:
            return await self._launch_sandboxed_process(
                shell_path, shell_args, work_dir, policy, env
            )
        except OSError as e:
            logger.warning(f"AppContainer process launch failed: {e}")
            return None

    async def _ensure_container(self, policy: SandboxPolicy, work_dir: str) -> None:
        """Create or reuse AppContainer profile with matching ACLs."""
        from myrm_agent_harness.toolkits.code_execution.sandbox.providers._win32_defs import (
            create_appcontainer_profile,
        )

        fingerprint = _compute_policy_fingerprint(policy, work_dir)

        if self._container_sid and self._acl_fingerprint == fingerprint:
            return

        container_name = f"{_PROFILE_PREFIX}{fingerprint}"

        try:
            sid = create_appcontainer_profile(container_name)
        except OSError as e:
            raise OSError(f"Failed to create AppContainer profile: {e}") from e

        if self._acl_fingerprint != fingerprint:
            success = await _apply_acls(policy, work_dir, sid)
            if not success:
                logger.warning("Some ACL grants failed; sandbox may have limited access")

        self._container_name = container_name
        self._container_sid = sid
        self._acl_fingerprint = fingerprint

    async def _launch_sandboxed_process(
        self,
        shell_path: str,
        shell_args: tuple[str, ...],
        work_dir: str,
        policy: SandboxPolicy,
        env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        """Launch shell inside AppContainer via CreateProcessW."""
        from myrm_agent_harness.toolkits.code_execution.sandbox.providers._win32_defs import (
            CREATE_NO_WINDOW,
            CREATE_UNICODE_ENVIRONMENT,
            EXTENDED_STARTUPINFO_PRESENT,
            PROCESS_INFORMATION,
            SECURITY_CAPABILITIES,
            STARTF_USESTDHANDLES,
            STARTUPINFOEXW,
            build_capabilities,
            build_env_block,
            create_attribute_list,
            create_pipe,
            string_to_sid,
            wrap_handles_as_process,
        )

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        assert self._container_sid is not None

        stdin_read, stdin_write = create_pipe(kernel32, inherit_read=True)
        stdout_read, stdout_write = create_pipe(kernel32, inherit_read=False)

        try:
            container_psid = string_to_sid(self._container_sid)
            cap_sids, cap_array = build_capabilities(policy)

            sec_cap = SECURITY_CAPABILITIES()
            sec_cap.AppContainerSid = container_psid
            sec_cap.Capabilities = cap_array
            sec_cap.CapabilityCount = len(cap_sids)
            sec_cap.Reserved = 0

            attr_list = create_attribute_list(kernel32, sec_cap)

            si_ex = STARTUPINFOEXW()
            si_ex.StartupInfo.cb = ctypes.sizeof(si_ex)
            si_ex.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            si_ex.StartupInfo.hStdInput = stdin_read
            si_ex.StartupInfo.hStdOutput = stdout_write
            si_ex.StartupInfo.hStdError = stdout_write
            si_ex.lpAttributeList = attr_list

            env_block = build_env_block(env)
            cmd_line = f'"{shell_path}" {" ".join(shell_args)}'

            pi = PROCESS_INFORMATION()
            creation_flags = (
                EXTENDED_STARTUPINFO_PRESENT
                | CREATE_UNICODE_ENVIRONMENT
                | CREATE_NO_WINDOW
            )

            success = kernel32.CreateProcessW(
                None, cmd_line, None, None, True,
                creation_flags, env_block, work_dir,
                ctypes.byref(si_ex), ctypes.byref(pi),
            )

            if not success:
                err = ctypes.get_last_error()
                raise OSError(f"CreateProcessW failed: error {err}")

            kernel32.CloseHandle(pi.hThread)
            kernel32.CloseHandle(stdin_read)
            kernel32.CloseHandle(stdout_write)

            return await wrap_handles_as_process(
                pi.hProcess, pi.dwProcessId, stdin_write, stdout_read, kernel32
            )

        except Exception:
            kernel32.CloseHandle(stdin_read)
            kernel32.CloseHandle(stdin_write)
            kernel32.CloseHandle(stdout_read)
            kernel32.CloseHandle(stdout_write)
            raise

    def cleanup(self) -> None:
        """Clean up AppContainer profile on application exit."""
        if not self._container_name:
            return

        from myrm_agent_harness.toolkits.code_execution.sandbox.providers._win32_defs import (
            delete_appcontainer_profile,
        )

        if self._container_name:
            delete_appcontainer_profile(self._container_name)
            self._container_name = None
            self._container_sid = None


class AppContainerProcess:
    """Minimal asyncio.subprocess.Process-compatible wrapper for AppContainer processes."""

    def __init__(
        self,
        handle: ctypes.wintypes.HANDLE,
        pid: int,
        stdin: asyncio.StreamWriter,
        stdout: asyncio.StreamReader,
        kernel32: Any,
    ) -> None:
        self._handle = handle
        self.pid = pid
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = None
        self.returncode: int | None = None
        self._kernel32 = kernel32

    async def wait(self) -> int:
        """Wait for process to terminate."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._blocking_wait)
        return self.returncode  # type: ignore[return-value]

    def _blocking_wait(self) -> None:
        self._kernel32.WaitForSingleObject(self._handle, 0xFFFFFFFF)
        exit_code = ctypes.wintypes.DWORD()
        self._kernel32.GetExitCodeProcess(self._handle, ctypes.byref(exit_code))
        self.returncode = exit_code.value

    def send_signal(self, signal: int) -> None:
        """Terminate the process."""
        self._kernel32.TerminateProcess(self._handle, 1)

    def terminate(self) -> None:
        self.send_signal(1)

    def kill(self) -> None:
        self.send_signal(9)

    async def communicate(
        self, input: bytes | None = None  # noqa: A002
    ) -> tuple[bytes, bytes]:
        """Send input and read all output."""
        if input and self.stdin:
            self.stdin.write(input)
            await self.stdin.drain()
            self.stdin.close()

        stdout_data = await self.stdout.read(-1) if self.stdout else b""
        await self.wait()
        return stdout_data, b""

    def __del__(self) -> None:
        if self._handle:
            try:
                self._kernel32.CloseHandle(self._handle)
            except (OSError, TypeError):
                pass
