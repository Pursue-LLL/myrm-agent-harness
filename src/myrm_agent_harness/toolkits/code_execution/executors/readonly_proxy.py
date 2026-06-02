"""Read-only executor proxy for Adversarial Sandbox Verifier.

Provides zero-copy isolation by wrapping an existing CodeExecutor and:
1. Intercepting native file writes to raise PermissionError.
2. Modifying ExecutionContext to enforce OS-level sandbox readonly mode.

[INPUT]
- toolkits.code_execution.executors.base::CodeExecutor, CodeExecutorMiddleware (POS: Code executor base classes.)
- toolkits.code_execution.sandbox::detect_sandbox_provider (POS: Sandbox provider detection and status reporting.)

[OUTPUT]
- ReadonlyExecutorProxy: Executor middleware that enforces read-only access and tracks execution.

[POS]
Read-only executor proxy for Adversarial Sandbox Verifier.
"""

from collections.abc import AsyncIterator

from myrm_agent_harness.toolkits.code_execution.executors.base import (
    CodeExecutor,
    CodeExecutorMiddleware,
    ExecutionContext,
    ExecutionResult,
)


class ReadonlyExecutorProxy(CodeExecutorMiddleware):
    """Executor middleware that enforces read-only access.

    Used by the Adversarial Sandbox Verifier to prevent accidental modifications
    to the workspace while still allowing it to run tests and read files.
    """

    def __init__(self, inner: CodeExecutor):
        super().__init__(inner)
        self.has_executed_code: bool = False

    def _enforce_readonly_context(self, context: ExecutionContext) -> ExecutionContext:
        """Modify context to enforce readonly mode at OS level."""
        # Create a shallow copy of the context to avoid mutating the original
        import dataclasses

        new_context = dataclasses.replace(context)
        new_context.readonly_workspace = True

        # Append suffix to session_id to prevent reusing the worker's writable bash session
        if new_context.session_id:
            new_context.session_id = f"{new_context.session_id}_readonly"
        else:
            new_context.session_id = "readonly_session"

        return new_context

    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        self.has_executed_code = True
        return await self.inner.execute(self._enforce_readonly_context(context))

    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        self.has_executed_code = True
        from myrm_agent_harness.toolkits.code_execution.sandbox import detect_sandbox_provider
        _provider, status = detect_sandbox_provider()
        if not status.enabled:
            return ExecutionResult(
                success=False,
                error="[Security Fallback] Bash execution is strictly disabled in Read-Only Sandbox because OS-level isolation is unavailable on this host. Use python execution or read tools.",
                stderr="[Security Fallback] Bash execution disabled.",
                exit_code=1
            )
        return await self.inner.execute_bash(self._enforce_readonly_context(context))

    async def execute_bash_stream(
        self, context: ExecutionContext
    ) -> AsyncIterator[str]:
        self.has_executed_code = True
        from myrm_agent_harness.toolkits.code_execution.sandbox import detect_sandbox_provider
        _provider, status = detect_sandbox_provider()
        if not status.enabled:
            yield "[Security Fallback] Bash execution is strictly disabled in Read-Only Sandbox because OS-level isolation is unavailable on this host."
            return

        async for chunk in self.inner.execute_bash_stream(
            self._enforce_readonly_context(context)
        ):
            yield chunk

    # Native file write operations intercepted

    async def write_file(self, path: str, content: str) -> None:
        raise PermissionError(
            f"Write denied: verifier is running in read-only sandbox — {path}"
        )

    async def write_file_bytes(self, path: str, content: bytes) -> None:
        raise PermissionError(
            f"Write denied: verifier is running in read-only sandbox — {path}"
        )

    async def write_file_atomic(self, path: str, content: str) -> None:
        raise PermissionError(
            f"Write denied: verifier is running in read-only sandbox — {path}"
        )

    async def write_file_bytes_atomic(self, path: str, content: bytes) -> None:
        raise PermissionError(
            f"Write denied: verifier is running in read-only sandbox — {path}"
        )

    async def append_file(self, path: str, content: str) -> None:
        raise PermissionError(
            f"Write denied: verifier is running in read-only sandbox — {path}"
        )

    async def delete_file(self, path: str) -> None:
        raise PermissionError(
            f"Delete denied: verifier is running in read-only sandbox — {path}"
        )

    async def mkdir(self, path: str) -> None:
        raise PermissionError(
            f"Mkdir denied: verifier is running in read-only sandbox — {path}"
        )
