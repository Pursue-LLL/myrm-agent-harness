"""Code executor base classes.

Defines the unified interface for code execution and file operations.
CodeExecutor is the single entry point for all execution operations.

Lifecycle: bind_workspace(path) -> execute()/execute_bash()/read_file()/... -> cleanup()

[INPUT]
- toolkits.code_execution.config::ExecutionConfig (POS: Code execution configuration layer. Defines execution modes, network policies, and runtime settings for the Agent-in-Sandbox architecture.)

[OUTPUT]
- CodeExecutor: Abstract base class for code executors.
- CodeExecutorMiddleware: Executor middleware base class (decorator pattern).
- get_executor: Return the current executor for this async context, or ``...
- set_executor: Bind (or clear) the executor for the current async context.
- reset_executor: Restore a previous executor binding from a ContextVar token.
- require_executor: Return the current executor, raising if unavailable.

[POS]
Code executor base classes.
"""

import logging
import shlex
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextvars import ContextVar, Token
from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    MCPCommunicationConfig,
    MCPConfigItem,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CodeExecutor",
    "CodeExecutorMiddleware",
    "ExecutionContext",
    "ExecutionMetrics",
    "ExecutionResult",
    "MCPCommunicationConfig",
    "MCPConfigItem",
    "get_executor",
    "require_executor",
    "reset_executor",
    "set_executor",
]


class CodeExecutor(ABC):
    """Abstract base class for code executors.

    Interface design:
    - execute() and execute_bash() are the core abstract methods
    - File operations have default implementations via execute_bash()
    - LocalExecutor overrides file methods with native pathlib I/O

    Lifecycle: bind_workspace(path) -> execute()/read_file()/... -> cleanup()

    Metrics: Each executor instance maintains an ExecutionMetrics object
    that accumulates execution statistics (counts, timings, error distribution).
    Access via ``executor.metrics.to_dict()`` for structured export.
    """

    def __init__(self, config: ExecutionConfig | None = None):
        self.config = config
        self._workspace_path: str | None = None
        self.metrics = ExecutionMetrics()

    @property
    def workspace_path(self) -> str:
        if self._workspace_path is None:
            raise RuntimeError("Workspace not bound. Call bind_workspace() first.")
        return self._workspace_path

    def bind_workspace(self, workspace_path: str) -> None:
        """Bind this executor to a workspace directory."""
        self._workspace_path = workspace_path

    @abstractmethod
    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute Python code."""
        ...

    @abstractmethod
    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        """Execute a Bash command."""
        ...

    async def execute_bash_stream(
        self, context: ExecutionContext
    ) -> AsyncIterator[str]:
        """Execute a Bash command with real-time output streaming.

        Yields output chunks as they become available. Subclasses should override
        for true streaming via subprocess PIPE readline. The default implementation
        falls back to batch execution and yields the full output at once.

        Args:
            context: Execution context (code field is the Bash command).

        Yields:
            Output chunks (stdout lines).
        """
        result = await self.execute_bash(context)
        if result.stdout:
            yield result.stdout
        if result.stderr:
            yield result.stderr

    def _log_context_file_access(
        self, resolved_path: str, success: bool = True
    ) -> None:
        """Log context file access for offload mechanism validation."""
        if resolved_path.startswith(".context/") or "/.context/" in resolved_path:
            if success:
                logger.info(
                    "CONTEXT_ACCESS path=%s method=read_file success=true",
                    resolved_path,
                )
            else:
                logger.warning(
                    "CONTEXT_ACCESS path=%s method=read_file success=false",
                    resolved_path,
                )

    async def read_file(self, path: str) -> str:
        """Read a file from the execution environment.

        Automatically decompresses gzip files (.gz extension).
        Subclasses can override for native I/O performance.
        """
        safe = await self.resolve_path(path)
        self._log_context_file_access(safe, success=True)

        if safe.endswith(".gz"):
            import gzip
            from base64 import b64decode

            result = await self._exec_bash(f"base64 '{safe}'")
            if not result.success:
                self._log_context_file_access(safe, success=False)
                raise FileNotFoundError(
                    f"Cannot read '{path}': {result.error or result.stderr}"
                )

            compressed_data = b64decode(result.stdout.strip())
            return gzip.decompress(compressed_data).decode("utf-8")

        result = await self._exec_bash(f"cat '{safe}'")
        if not result.success:
            self._log_context_file_access(safe, success=False)
            raise FileNotFoundError(
                f"Cannot read '{path}': {result.error or result.stderr}"
            )
        return result.stdout

    async def read_file_bytes(self, path: str) -> bytes:
        """Read a file as bytes."""
        safe = await self.resolve_path(path)
        result = await self._exec_bash(f"base64 '{safe}'")
        if not result.success:
            raise FileNotFoundError(
                f"Cannot read '{path}': {result.error or result.stderr}"
            )
        from base64 import b64decode

        return b64decode(result.stdout.strip())

    async def write_file(self, path: str, content: str) -> None:
        """Write text content to a file."""
        from base64 import b64encode

        safe = await self.resolve_path(path)
        parent = str(Path(safe).parent)
        encoded = b64encode(content.encode()).decode()
        await self._exec_bash(
            f"mkdir -p '{parent}' && echo '{encoded}' | base64 -d > '{safe}'"
        )

    async def write_file_bytes(self, path: str, content: bytes) -> None:
        """Write binary content to a file."""
        from base64 import b64encode

        safe = await self.resolve_path(path)
        parent = str(Path(safe).parent)
        encoded = b64encode(content).decode()
        await self._exec_bash(
            f"mkdir -p '{parent}' && echo '{encoded}' | base64 -d > '{safe}'"
        )

    async def write_file_atomic(self, path: str, content: str) -> None:
        """Atomically replace a text file through a same-directory temporary file."""
        await self._write_file_atomic(path, content)

    async def write_file_bytes_atomic(self, path: str, content: bytes) -> None:
        """Atomically replace a binary file through a same-directory temporary file."""
        await self._write_file_atomic(path, content)

    async def _write_file_atomic(self, path: str, content: str | bytes) -> None:
        target = await self.resolve_path(path)
        target_path = Path(target)
        tmp_name = f".atomic_{uuid.uuid4().hex}_{target_path.name}"
        tmp_relative = str(Path(path).parent / tmp_name)
        if tmp_relative.startswith("./"):
            tmp_relative = tmp_relative[2:]

        if isinstance(content, bytes):
            await self.write_file_bytes(tmp_relative, content)
        else:
            await self.write_file(tmp_relative, content)

        tmp_path = await self.resolve_path(tmp_relative)
        result = await self._exec_bash(
            "mkdir -p "
            f"{shlex.quote(str(target_path.parent))} && "
            f"mv -f {shlex.quote(tmp_path)} {shlex.quote(target)}"
        )
        if not result.success:
            await self._exec_bash(f"rm -f {shlex.quote(tmp_path)}")
            raise OSError(
                f"Atomic replace failed for '{path}': {result.error or result.stderr}"
            )

    async def append_file(self, path: str, content: str) -> None:
        """Append text content to a file."""
        from base64 import b64encode

        safe = await self.resolve_path(path)
        encoded = b64encode(content.encode()).decode()
        await self._exec_bash(f"echo '{encoded}' | base64 -d >> '{safe}'")

    async def delete_file(self, path: str) -> None:
        """Delete a file."""
        safe = await self.resolve_path(path)
        await self._exec_bash(f"rm -f '{safe}'")

    async def file_exists(self, path: str) -> bool:
        """Check if a file or directory exists."""
        safe = await self.resolve_path(path)
        result = await self._exec_bash(f"test -e '{safe}' && echo 1 || echo 0")
        return result.stdout.strip() == "1"

    async def is_file(self, path: str) -> bool:
        safe = await self.resolve_path(path)
        result = await self._exec_bash(f"test -f '{safe}' && echo 1 || echo 0")
        return result.stdout.strip() == "1"

    async def is_dir(self, path: str) -> bool:
        safe = await self.resolve_path(path)
        result = await self._exec_bash(f"test -d '{safe}' && echo 1 || echo 0")
        return result.stdout.strip() == "1"

    async def mkdir(self, path: str) -> None:
        """Create a directory (including parents)."""
        safe = await self.resolve_path(path)
        await self._exec_bash(f"mkdir -p '{safe}'")

    async def list_files(self, path: str = ".", pattern: str = "*") -> list[str]:
        """List files matching a pattern."""
        safe = await self.resolve_path(path)
        result = await self._exec_bash(
            f"find '{safe}' -maxdepth 1 -name '{pattern}' -type f"
        )
        return (
            [line for line in result.stdout.strip().splitlines() if line]
            if result.success
            else []
        )

    async def grep(
        self,
        pattern: str,
        path: str = ".",
        use_regex: bool = False,
        case_sensitive: bool = True,
    ) -> str:
        """Search for text within the workspace."""
        safe = await self.resolve_path(path)
        escaped_pattern = pattern.replace("'", "'\\''")

        flags = ["-rn"]
        if not use_regex:
            flags.append("F")
        if not case_sensitive:
            flags.append("i")

        flags_str = "-" + "".join(flags)
        result = await self._exec_bash(
            f"grep {flags_str} '{escaped_pattern}' '{safe}' || true"
        )
        return result.stdout

    async def glob_files(self, pattern: str) -> list[str]:
        """Find files matching a glob pattern."""
        result = await self._exec_bash(
            f"find '{self.workspace_path}' -path '{pattern}' -type f"
        )
        return (
            [line for line in result.stdout.strip().splitlines() if line]
            if result.success
            else []
        )

    async def resolve_path(self, relative_path: str) -> str:
        """Resolve a relative path to absolute, with path traversal detection."""
        wp = Path(self.workspace_path).resolve()

        clean = relative_path
        if clean.startswith("/workspace"):
            clean = clean[len("/workspace") :].lstrip("/")
            clean = clean or "."

        if Path(clean).is_absolute():
            resolved = Path(clean).resolve()
        else:
            resolved = (wp / clean).resolve()

        if not str(resolved).startswith(str(wp)):
            raise ValueError(
                f"Path traversal detected: {relative_path} (workspace is {wp})"
            )
        return str(resolved)

    async def is_available(self) -> bool:
        return True

    def get_executor_name(self) -> str:
        return (
            self.__class__.__name__.removesuffix("Executor") or self.__class__.__name__
        )

    def get_mcp_communication_config(self) -> MCPCommunicationConfig | None:
        return None

    async def save_workspace(self, session_id: str, storage_path: str) -> bool:
        return False

    async def restore_workspace(self, session_id: str, storage_path: str) -> bool:
        return False

    async def _exec_bash(self, command: str) -> ExecutionResult:
        """Internal bash execution helper for default file operations."""
        ctx = ExecutionContext(code=command, work_dir=self.workspace_path)
        return await self.execute_bash(ctx)

    def _extract_python_code_from_bash(self, command: str) -> str | None:
        from myrm_agent_harness.toolkits.code_execution.python_extractor import (
            extract_python_from_bash,
        )

        return extract_python_from_bash(command)


class CodeExecutorMiddleware(CodeExecutor):
    """Executor middleware base class (decorator pattern).

    Injects policy checks before/after execution (e.g. command blocklist, timeout, path restrictions).
    Multiple middlewares can be composed into a policy chain.
    """

    def __init__(self, inner: CodeExecutor):
        self.inner = inner
        super().__init__(config=inner.config)

    @property
    def metrics(self) -> ExecutionMetrics:  # type: ignore[override]
        return self.inner.metrics

    @metrics.setter
    def metrics(self, value: ExecutionMetrics) -> None:
        self.inner.metrics = value

    @property
    def workspace_path(self) -> str:
        return self.inner.workspace_path

    def bind_workspace(self, workspace_path: str) -> None:
        self.inner.bind_workspace(workspace_path)

    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        return await self.inner.execute(context)

    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        return await self.inner.execute_bash(context)

    async def execute_bash_stream(
        self, context: ExecutionContext
    ) -> AsyncIterator[str]:
        async for chunk in self.inner.execute_bash_stream(context):
            yield chunk

    async def read_file(self, path: str) -> str:
        return await self.inner.read_file(path)

    async def read_file_bytes(self, path: str) -> bytes:
        return await self.inner.read_file_bytes(path)

    async def write_file(self, path: str, content: str) -> None:
        await self.inner.write_file(path, content)

    async def write_file_bytes(self, path: str, content: bytes) -> None:
        await self.inner.write_file_bytes(path, content)

    async def append_file(self, path: str, content: str) -> None:
        await self.inner.append_file(path, content)

    async def delete_file(self, path: str) -> None:
        await self.inner.delete_file(path)

    async def file_exists(self, path: str) -> bool:
        return await self.inner.file_exists(path)

    async def is_file(self, path: str) -> bool:
        return await self.inner.is_file(path)

    async def is_dir(self, path: str) -> bool:
        return await self.inner.is_dir(path)

    async def mkdir(self, path: str) -> None:
        await self.inner.mkdir(path)

    async def list_files(self, path: str = ".", pattern: str = "*") -> list[str]:
        return await self.inner.list_files(path, pattern)

    async def grep(
        self,
        pattern: str,
        path: str = ".",
        use_regex: bool = False,
        case_sensitive: bool = True,
    ) -> str:
        return await self.inner.grep(
            pattern, path, use_regex=use_regex, case_sensitive=case_sensitive
        )

    async def glob_files(self, pattern: str) -> list[str]:
        return await self.inner.glob_files(pattern)

    async def resolve_path(self, relative_path: str) -> str:
        return await self.inner.resolve_path(relative_path)

    async def is_available(self) -> bool:
        return await self.inner.is_available()

    def get_executor_name(self) -> str:
        return self.inner.get_executor_name()

    def get_mcp_communication_config(self) -> MCPCommunicationConfig | None:
        return self.inner.get_mcp_communication_config()

    async def save_workspace(self, session_id: str, storage_path: str) -> bool:
        return await self.inner.save_workspace(session_id, storage_path)

    async def restore_workspace(self, session_id: str, storage_path: str) -> bool:
        return await self.inner.restore_workspace(session_id, storage_path)


# ---------------------------------------------------------------------------
# Executor ContextVar — runtime instance management
# ---------------------------------------------------------------------------
# All tools share a single executor per async context. ContextVar avoids
# LangGraph checkpoint serialization issues (executor is not JSON-serializable).

_executor_var: ContextVar[CodeExecutor | None] = ContextVar("executor", default=None)


def get_executor() -> CodeExecutor | None:
    """Return the current executor for this async context, or ``None``."""
    return _executor_var.get()


def set_executor(executor: CodeExecutor | None) -> Token[CodeExecutor | None]:
    """Bind (or clear) the executor for the current async context."""
    return _executor_var.set(executor)


def reset_executor(token: Token[CodeExecutor | None]) -> None:
    """Restore a previous executor binding from a :func:`set_executor` token."""
    _executor_var.reset(token)


def require_executor() -> CodeExecutor:
    """Return the current executor, raising if unavailable.

    Raises:
        RuntimeError: No executor bound in the current async context.
    """
    executor = _executor_var.get()
    if executor is None:
        raise RuntimeError(
            "CodeExecutor not available. Call set_executor() to bind an executor to the current async context first."
        )
    return executor


# ---------------------------------------------------------------------------
# Session-level executor stash (survives LangGraph ContextVar loss)
# ---------------------------------------------------------------------------
# LangGraph's CompiledGraph.astream() may run tool nodes in isolated contexts
# where ContextVars set during setup_workspace are not visible. This dict
# provides a fallback lookup by session_id so tools can self-heal.

_session_executor_stash: dict[str, CodeExecutor] = {}


def stash_executor_for_session(session_id: str, executor: CodeExecutor) -> None:
    """Store executor reference keyed by session_id for cross-context recovery."""
    _session_executor_stash[session_id] = executor


def get_stashed_executor(session_id: str) -> CodeExecutor | None:
    """Retrieve stashed executor by session_id, or None."""
    return _session_executor_stash.get(session_id)


def clear_stashed_executor(session_id: str) -> None:
    """Remove stashed executor entry on session teardown."""
    _session_executor_stash.pop(session_id, None)
