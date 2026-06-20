"""Local code executor orchestrator.

[INPUT]
local._file_ops::LocalFileOpsMixin (POS: Native file I/O via pathlib with read-only guard)
local._python_subprocess::run_python_subprocess (POS: Python subprocess with sandbox and timeout)
local._background_spawn::spawn_background_process (POS: Background process spawning with sandbox)
executors.common::CommandRewriter, VenvManager, ExecutionHelper (POS: Shared execution utilities)
executors.base::CodeExecutor (POS: Code executor abstract base)
code_execution.config::ExecutionConfig (POS: Execution configuration layer)
code_execution.session::LocalPersistentSession (POS: Concrete persistent shell session)

[OUTPUT]
LocalExecutor: Unified local executor for Python code and Bash commands.

[POS]
Local code execution orchestrator. Coordinates Python/Bash execution,
persistent session lifecycle, workspace binding, and composed services
(VenvManager, CommandRewriter, FileScanner, ExecutionHelper).
"""

import asyncio  # noqa: F401  # exposed as ``executor.asyncio`` for test monkey-patching
import logging
import os
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Self

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.base import (
    CodeExecutor,
    ExecutionContext,
    ExecutionResult,
)
from myrm_agent_harness.toolkits.code_execution.executors.common import (
    CommandRewriter,
    ExecutionHelper,
    LocalFilesScanner,
    VenvManager,
    extract_short_error,
    generate_wrapper_script,
    handle_execution_error,
)
from myrm_agent_harness.toolkits.code_execution.executors.local._file_ops import (
    LocalFileOpsMixin,
)
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    AsyncProcessProtocol,
)
from myrm_agent_harness.toolkits.code_execution.utils import WorkspacePathResolver

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.session import (
        LocalPersistentSession,
    )

logger = logging.getLogger(__name__)


from myrm_agent_harness.toolkits.code_execution.interceptor import trigger_destructive_action_hook
from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import is_destructive_command


class LocalExecutor(LocalFileOpsMixin, CodeExecutor):
    """Local code executor.

    Responsibilities:
    - Execute Python code and Bash commands
    - Manage workspace binding
    - Coordinate composed services

    Composed services:
    - VenvManager: virtual environment management
    - CommandRewriter: command path rewriting
    - FileScanner: generated file scanning
    - ExecutionHelper: logging and formatting utilities
    - LocalPersistentSession: persistent Bash sessions

    File operations (read/write/grep/glob) are provided by LocalFileOpsMixin.
    """

    def __init__(self, config: ExecutionConfig, workspace_path: str | None = None):
        super().__init__(config)
        # Narrow ``CodeExecutor.config: ExecutionConfig | None`` to the strict
        # ``ExecutionConfig`` we just received so mypy can resolve ``.local``
        # without union-attr noise.
        self.config: ExecutionConfig = config

        self._venv_manager = VenvManager(config)
        self._command_rewriter = CommandRewriter()
        self._file_scanner = LocalFilesScanner()
        self._helper = ExecutionHelper()

        self._current_workspace: Path | None = None
        self._readonly_paths: list[str] = []
        self._bash_sessions: dict[str, LocalPersistentSession] = {}

        if workspace_path:
            self.bind_workspace(workspace_path)

    def bind_workspace(self, workspace_path: str) -> None:
        path = Path(workspace_path)
        if self._current_workspace == path:
            return

        super().bind_workspace(workspace_path)
        self._current_workspace = path
        path.mkdir(parents=True, exist_ok=True)

        logger.debug(f" LocalExecutor: bound to workspace {workspace_path}")

    def add_readonly_path(self, path: str) -> None:
        """Register a read-only path (local mode)."""
        self._readonly_paths.append(path)

    def _resolve_work_dir(self, work_dir: str, workspace_root: Path | None) -> Path | None:
        """Resolve abstract paths (e.g. /workspace/...) to local filesystem paths.

        In container environments these paths are used directly; LocalExecutor
        adapts them to the host filesystem via WorkspacePathResolver.

        Args:
            work_dir: Abstract working directory path.
            workspace_root: Actual workspace root directory.

        Returns:
            Resolved local path, or None if resolution fails.
        """
        return WorkspacePathResolver.to_local_path(work_dir, workspace_root)

    @handle_execution_error("LocalExecutor")
    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute Python code (stateless — each call runs in a fresh subprocess)."""
        start_time = time.time()

        self._helper.log_execution_start("LocalExecutor", "Python", context.code)

        self._setup_workspace(context.workspace_root)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix="_user_code.py",
            delete=False,
            encoding="utf-8",
        ) as code_file:
            code_file.write(context.code)
            code_file_path = Path(code_file.name)

        wrapper_content = generate_wrapper_script(
            str(code_file_path),
            allow_network=context.allow_network,
            allowed_hosts=context.allowed_hosts,
            timeout=context.timeout or self.config.local.max_execution_time,
            memory_limit_mb=self.config.local.max_memory_mb,
            max_output_bytes=self.config.local.max_output_bytes,
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix="_wrapper.py",
            delete=False,
            encoding="utf-8",
        ) as wrapper_file:
            wrapper_file.write(wrapper_content)
            wrapper_path = Path(wrapper_file.name)

        try:
            effective_cwd = self._resolve_work_dir(
                context.work_dir,
                (Path(context.workspace_root) if context.workspace_root else self._current_workspace),
            )

            result = await self._run_subprocess(
                wrapper_path,
                context.timeout or 300,
                cwd=effective_cwd,
                env=context.env,
                allow_network=context.allow_network,
                context=context,
            )

            execution_time = time.time() - start_time

            generated_files = await self._file_scanner.scan(
                start_time,
                self._current_workspace,
            )

            if result.success:
                self._helper.log_execution_success("LocalExecutor", execution_time)

            final_result = ExecutionResult(
                success=result.success,
                result=result.result,
                stdout=result.stdout,
                stderr=result.stderr,
                error=extract_short_error(result.error) if result.error else None,
                execution_time=execution_time,
                container_id=context.session_id,
                generated_files=generated_files,
            )

            self.metrics.record(final_result, "python")
            return final_result
        finally:
            code_file_path.unlink(missing_ok=True)
            wrapper_path.unlink(missing_ok=True)

    async def _run_subprocess(
        self,
        script_path: Path,
        timeout: int,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        allow_network: bool = True,
        context: ExecutionContext | None = None,
    ) -> ExecutionResult:
        """Execute a Python script via subprocess with sandbox and timeout."""
        from myrm_agent_harness.toolkits.code_execution.executors.local._python_subprocess import (
            run_python_subprocess,
        )

        python_executable = await self._venv_manager.get_python_executable()
        return await run_python_subprocess(
            script_path=script_path,
            timeout=timeout,
            python_executable=python_executable,
            cwd=cwd,
            env=env,
            allow_network=allow_network,
            context=context,
        )

    @handle_execution_error("LocalExecutor")
    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        """Execute a Bash command in a persistent session (state persists across calls)."""
        from myrm_agent_harness.toolkits.code_execution.security.validator import (
            validate_command,
        )

        start_time = time.time()
        command = context.code
        validation_command = getattr(context, "original_code", command) or command

        self._helper.log_execution_start("LocalExecutor", "Bash (Persistent)", command)

        # Resolve working directory
        workspace = Path(context.workspace_root) if context.workspace_root else self._current_workspace
        effective_cwd = self._resolve_work_dir(context.work_dir, workspace)

        # Security validation
        effective_allowed_hosts = None
        if context.allow_network and context.allowed_hosts is not None:
            effective_allowed_hosts = context.allowed_hosts

        validation_result = validate_command(
            validation_command,
            workspace_path=effective_cwd,
            additional_paths=self._get_venv_additional_paths(),
            allowed_hosts=effective_allowed_hosts,
        )

        if not validation_result.is_safe:
            error_msg = f"Command blocked for security reasons: {validation_result.reason}"
            logger.warning(f" [LocalExecutor] {error_msg}")
            blocked_result = ExecutionResult(
                success=False,
                error=error_msg,
                error_category="permission",
                stderr=error_msg,
                execution_time=time.time() - start_time,
            )
            self.metrics.record(blocked_result, "bash")
            return blocked_result

        # Trigger auto-snapshot hook if command is destructive
        if is_destructive_command(command):
            await trigger_destructive_action_hook(
                workspace_path=str(self._current_workspace) if self._current_workspace else "/tmp",
                action_type="bash",
                payload={"command": command, "session_id": context.session_id},
            )

        self._setup_workspace(str(effective_cwd) if effective_cwd else None)

        command = await self._prepare_bash_command(command)

        # Build environment
        env = self._build_bash_env(context.env)

        session_key = context.session_id or "default"
        session = await self._get_or_create_bash_session(
            session_key,
            str(self._current_workspace) if self._current_workspace else "/tmp",
            context.timeout or 300,
            env,
            allow_network=context.allow_network,
            readonly_workspace=context.readonly_workspace,
        )

        timeout = context.timeout or self.config.local.max_execution_time
        session_result = await session.execute(command, timeout)

        execution_time = time.time() - start_time

        generated_files = await self._file_scanner.scan(
            start_time,
            self._current_workspace,
        )

        if session_result.success:
            self._helper.log_execution_success("LocalExecutor", execution_time)
        else:
            cmd_preview = command[:200] + "..." if len(command) > 200 else command
            logger.warning(
                " [LocalExecutor] Bash exit code: %d (%s) | cmd: %s",
                session_result.exit_code,
                self._helper.format_execution_time(execution_time),
                cmd_preview,
            )
            if session_result.stderr:
                logger.warning(f" [LocalExecutor] Bash stderr: {session_result.stderr}")
            if session_result.stdout:
                logger.info(f" [LocalExecutor] Bash stdout: {session_result.stdout}")

        final_result = ExecutionResult(
            success=session_result.success,
            result=session_result.exit_code,
            stdout=session_result.stdout,
            stderr=session_result.stderr,
            error=session_result.error,
            execution_time=execution_time,
            container_id=context.session_id,
            generated_files=generated_files,
            exit_code=session_result.exit_code,
        )
        self.metrics.record(final_result, "bash")
        return final_result

    async def execute_bash_stream(self, context: ExecutionContext) -> AsyncIterator[str]:
        """Execute a Bash command with real-time line-by-line output streaming."""
        from myrm_agent_harness.toolkits.code_execution.security.validator import (
            validate_command,
        )

        command = context.code
        workspace = Path(context.workspace_root) if context.workspace_root else self._current_workspace
        effective_cwd = self._resolve_work_dir(context.work_dir, workspace)

        effective_allowed_hosts = None
        if context.allow_network and context.allowed_hosts is not None:
            effective_allowed_hosts = context.allowed_hosts

        validation_result = validate_command(
            command,
            workspace_path=effective_cwd,
            additional_paths=self._get_venv_additional_paths(),
            allowed_hosts=effective_allowed_hosts,
        )

        if not validation_result.is_safe:
            yield f"[ERROR] Command blocked: {validation_result.reason}\n"
            return

        self._setup_workspace(str(effective_cwd) if effective_cwd else None)
        command = await self._prepare_bash_command(command)
        env = self._build_bash_env(context.env)

        session_key = context.session_id or "default"
        session = await self._get_or_create_bash_session(
            session_key,
            str(self._current_workspace) if self._current_workspace else "/tmp",
            context.timeout or 300,
            env,
            allow_network=context.allow_network,
            readonly_workspace=context.readonly_workspace,
        )

        timeout = context.timeout or self.config.local.max_execution_time
        async for chunk in session.execute_stream(command, timeout):
            yield chunk

    async def spawn_background_process(self, context: ExecutionContext) -> AsyncProcessProtocol:
        """Spawn a long-running background process with full-duplex streams.

        Uses OS-level sandboxing (e.g., bwrap) if available to isolate the process.
        Implements pristine environment sanitization and process tree killing.
        """
        from myrm_agent_harness.toolkits.code_execution.executors.local._background_spawn import (
            spawn_background_process,
        )

        return await spawn_background_process(
            context=context,
            current_workspace=self._current_workspace,
            resolve_work_dir=self._resolve_work_dir,
            setup_workspace=self._setup_workspace,
            venv_path=self._venv_manager.get_venv_path(),
        )

    async def _get_or_create_bash_session(
        self,
        session_key: str,
        workspace_path: str,
        timeout: int,
        env: dict[str, str],
        allow_network: bool = True,
        readonly_workspace: bool = False,
    ) -> "LocalPersistentSession":
        """Get existing healthy session or create a new one."""
        from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
            SandboxPolicy,
        )
        from myrm_agent_harness.toolkits.code_execution.session import (
            LocalPersistentSession,
            SessionConfig,
        )

        if session_key in self._bash_sessions:
            session = self._bash_sessions[session_key]
            if session.is_alive:
                is_healthy = await session.check_health()
                if is_healthy:
                    logger.debug(f" [LocalExecutor] Reusing Bash session: {session_key}")
                    return session
                else:
                    logger.warning(f" [LocalExecutor] Unhealthy Bash session, restarting: {session_key}")
                    await session.close()
                    del self._bash_sessions[session_key]

        logger.info(f" [LocalExecutor] Creating new Bash session: {session_key}")
        config = SessionConfig(
            session_id=session_key,
            work_dir=workspace_path,
            timeout=timeout,
            env=env,
            max_memory_mb=self.config.local.max_memory_mb,
        )

        sandbox_policy = SandboxPolicy(
            writable_paths=("/tmp",) if readonly_workspace else (workspace_path,),
            allow_network=allow_network,
        )

        session = LocalPersistentSession(config, sandbox_policy=sandbox_policy)
        await session.start()
        self._bash_sessions[session_key] = session
        return session

    async def cleanup_bash_sessions(self) -> None:
        """Clean up all persistent Bash sessions."""
        if not self._bash_sessions:
            return

        logger.info(f" [LocalExecutor] Cleaning up {len(self._bash_sessions)} Bash sessions")
        for session_key, session in list(self._bash_sessions.items()):
            try:
                await session.close()
            except Exception as e:
                logger.warning(f" [LocalExecutor] Failed to close session {session_key}: {e}")
            finally:
                del self._bash_sessions[session_key]

    async def _prepare_bash_command(self, command: str) -> str:
        """Rewrite workspace paths and pip commands for the local environment."""
        command = self._command_rewriter.rewrite_workspace_paths(
            command,
            self._current_workspace,
        )
        return await self._venv_manager.rewrite_pip_command(command)

    def _build_bash_env(self, user_env: dict[str, str] | None) -> dict[str, str]:
        """Build sanitized environment with venv and user overrides."""
        from myrm_agent_harness.toolkits.code_execution.security.validator import (
            sanitize_env,
        )

        env = sanitize_env(os.environ.copy())

        venv_path = self._venv_manager.get_venv_path()
        if venv_path.exists():
            env["VIRTUAL_ENV"] = str(venv_path)
            venv_bin = str(venv_path / "bin")
            env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")

        if user_env:
            env.update(sanitize_env(user_env))
            logger.debug(f" User env vars: {list(user_env.keys())}")

        return env

    def _get_venv_additional_paths(self) -> list[Path] | None:
        """Return venv path for command security whitelist, if it exists."""
        venv_path = self._venv_manager.get_venv_path()
        if venv_path.exists():
            return [venv_path]
        return None

    def _setup_workspace(self, workspace_path: str | None) -> None:
        """Set up the workspace directory, creating it if needed."""
        if workspace_path:
            self._current_workspace = Path(workspace_path)
            self._current_workspace.mkdir(parents=True, exist_ok=True)

    async def is_available(self) -> bool:
        """Local executor is always available."""
        return True

    def get_executor_name(self) -> str:
        """Return the executor name."""
        return "LocalExecutor"

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit: clean up sessions."""
        await self.cleanup_bash_sessions()
