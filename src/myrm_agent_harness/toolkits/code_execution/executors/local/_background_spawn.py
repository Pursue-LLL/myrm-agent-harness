"""Background process spawning with sandbox and environment isolation.

[INPUT]
executors.base::ExecutionContext (POS: Code executor base classes)
executors.models::AsyncProcessProtocol (POS: Data models for code execution)
code_execution.sandbox::detect_sandbox_provider (POS: Sandbox detection and wrapping)
code_execution.security.validator::sanitize_env (POS: Environment sanitization)
executors.local._background_pty_spawn::try_spawn_background_pty (POS: POSIX PTY spawn adapter)

[OUTPUT]
spawn_background_process: Spawn a sandboxed background process with full-duplex streams.
PTY-first on POSIX hosts without OS sandbox; falls back to PIPE via `_background_pty_spawn.py`.

[POS]
Background process spawning. Handles sandbox wrapping, environment sanitization,
memory limits, process group management, non-interactive CI-mode environment
defaults (``CI`` / ``NO_COLOR`` / ``DEBIAN_FRONTEND`` / ``PYTHONUNBUFFERED``),
and an 8 MiB ``StreamReader.limit`` so multi-MB log lines (docker manifests,
pytest dumps) never trip ``LimitOverrunError`` and stall the reader.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionContext
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    AsyncProcessProtocol,
)

logger = logging.getLogger(__name__)


class _AsyncioProcessWrapper(AsyncProcessProtocol):
    """Adapts ``asyncio.subprocess.Process`` to ``AsyncProcessProtocol``."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc

    @property
    def stdin(self) -> object:
        return self._proc.stdin

    @property
    def stdout(self) -> object:
        return self._proc.stdout

    @property
    def stderr(self) -> object:
        return self._proc.stderr

    async def wait(self) -> int:
        return await self._proc.wait()

    def terminate(self) -> None:
        import signal

        from myrm_agent_harness.utils import os_compat

        os_compat.kill_process_group(self._proc.pid, signal.SIGTERM)

    def kill(self) -> None:
        import signal

        from myrm_agent_harness.utils import os_compat

        os_compat.kill_process_group(self._proc.pid, signal.SIGKILL)


async def spawn_background_process(
    context: ExecutionContext,
    current_workspace: Path | None,
    resolve_work_dir: Callable[[str, Path | None], Path | None],
    setup_workspace: Callable[[str | None], None],
    venv_path: Path,
) -> AsyncProcessProtocol:
    """Spawn a long-running background process with full-duplex streams.

    Uses OS-level sandboxing (e.g., bwrap) if available to isolate the process.
    Implements pristine environment sanitization and process tree killing.

    Args:
        context: Execution context with code, args, env, etc.
        current_workspace: Currently bound workspace path.
        resolve_work_dir: Callable to resolve abstract paths to local paths.
        setup_workspace: Callable to ensure workspace directory exists.
        venv_path: Path to the shared virtual environment.

    Returns:
        AsyncProcessProtocol wrapping the spawned subprocess.
    """
    from myrm_agent_harness.toolkits.code_execution.sandbox import (
        detect_sandbox_provider,
    )
    from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
        SandboxPolicy,
    )
    from myrm_agent_harness.toolkits.code_execution.security.validator import (
        sanitize_env,
    )

    workspace = Path(context.workspace_root) if context.workspace_root else current_workspace
    effective_cwd = resolve_work_dir(context.work_dir, workspace)
    setup_workspace(str(effective_cwd) if effective_cwd else None)

    base_env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "USER", "LANG", "LC_ALL")}
    env = sanitize_env(base_env)

    if venv_path.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        venv_bin = str(venv_path / "bin")
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")

    # Non-interactive defaults: a background spawn has no TTY by definition,
    # so we tell common toolchains to skip colour escapes (which corrupt the
    # progress parser), suppress interactive prompts (apt/debconf hangs are
    # silent killers) and act like a CI run (npm/yarn switch to predictable
    # output). ``setdefault`` lets the caller still override per-job.
    env.setdefault("CI", "true")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("FORCE_COLOR", "0")
    env.setdefault("TERM", "dumb")
    env.setdefault("DEBIAN_FRONTEND", "noninteractive")
    env.setdefault("PYTHONUNBUFFERED", "1")

    if context.env:
        env.update(context.env)

    cmd = context.code
    args = context.args or []

    work_dir_str = str(effective_cwd) if effective_cwd else "/tmp"
    provider, sandbox_status = detect_sandbox_provider()
    preexec_fn: Callable[[], None] | None = None

    if sandbox_status.enabled:
        policy = SandboxPolicy(
            writable_paths=(work_dir_str,),
            allow_network=context.allow_network,
        )
        wrapped_cmd, wrapped_args = provider.wrap_command(cmd, tuple(args), work_dir_str, policy)
        full_cmd_array = [wrapped_cmd, *wrapped_args]
        use_pty = False
    else:
        full_cmd_array = [cmd, *args]
        use_pty = True

        if context.max_memory_mb:
            mem_bytes = context.max_memory_mb * 1024 * 1024

            def _apply_memory_limit() -> None:
                import resource

                with suppress(ValueError, OSError):
                    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

            preexec_fn = _apply_memory_limit

    logger.info(f" [LocalExecutor] Spawning background: {' '.join(full_cmd_array)}")

    from myrm_agent_harness.utils import os_compat

    kwargs = os_compat.get_process_group_kwargs()
    if os.name != "nt" and preexec_fn:
        kwargs["preexec_fn"] = preexec_fn

    if use_pty:
        from myrm_agent_harness.toolkits.code_execution.executors.local._background_pty_spawn import (
            pty_spawn_eligible,
            try_spawn_background_pty,
        )

        if pty_spawn_eligible(sandbox_enabled=False):
            pty_proc = await try_spawn_background_pty(
                full_cmd_array=full_cmd_array,
                effective_cwd=effective_cwd,
                env=env,
                preexec_fn=preexec_fn,
                process_group_kwargs=kwargs,
            )
            if pty_proc is not None:
                return pty_proc
            logger.info(" [LocalExecutor] PTY spawn unavailable; falling back to PIPE")

    # The default StreamReader limit is 64 KiB. Real-world tools (docker
    # manifest JSON, pytest -vv dumps, Node heap dumps) easily exceed that
    # in a single line, raising ``LimitOverrunError`` which silently kills
    # the reader and loses every subsequent byte of the long-running job.
    # 8 MiB is comfortably above any organic line we have seen yet still
    # tiny relative to per-process RSS.
    kwargs.setdefault("limit", 8 * 1024 * 1024)
    process = await asyncio.create_subprocess_exec(
        *full_cmd_array,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(effective_cwd) if effective_cwd else None,
        env=env,
        **kwargs,
    )

    return _AsyncioProcessWrapper(process)
