"""Shadow Agent bulkhead isolation for background / review workloads.

Enforces execution-layer isolation via ContextVar-scoped executor wrapping:
- Blocks Python and Bash execution (no shell escape hatch).
- Restricts file mutations to skill/memory sidecar paths.
- Marks the async context as a shadow agent so approval middleware auto-denies.

[INPUT]
- toolkits.code_execution.executors.base::CodeExecutorMiddleware (POS: Executor middleware base class)
- middlewares._session_context::set_is_shadow_agent (POS: Middleware session context)

[OUTPUT]
- ShadowExecutorMiddleware: Restricted executor proxy for shadow workloads.
- restricted_shadow_context: Async context manager applying bulkhead isolation.

[POS]
Execution-layer bulkhead isolation for background shadow workloads.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.middlewares._session_context import (
    reset_is_shadow_agent,
    set_is_shadow_agent,
)
from myrm_agent_harness.toolkits.code_execution.executors.base import (
    CodeExecutorMiddleware,
    ExecutionContext,
    ExecutionResult,
    get_executor,
    reset_executor,
    set_executor,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

__all__ = [
    "ShadowExecutorMiddleware",
    "get_shadow_silent_mode",
    "restricted_shadow_context",
]

_shadow_silent_mode: ContextVar[bool] = ContextVar("shadow_silent_mode", default=False)

_ALLOWED_CONTEXT_PREFIX: str = ".context/"
_SKILL_ARTIFACT_NAMES: frozenset[str] = frozenset({"SKILL.md", ".stats.json", ".usage.json"})
_SKILL_SUPPORT_MARKERS: tuple[str, ...] = ("/references/", "/templates/", "/scripts/")


class ShadowSilentFilter(logging.Filter):
    """Drop log records emitted while shadow silent mode is active."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not _shadow_silent_mode.get()


_filter_attached = False


def _ensure_silent_filter() -> None:
    global _filter_attached
    if _filter_attached:
        return
    root_logger = logging.getLogger()
    silent_filter = ShadowSilentFilter()
    if not any(isinstance(item, ShadowSilentFilter) for item in root_logger.filters):
        root_logger.addFilter(silent_filter)
    for handler in root_logger.handlers:
        if not any(isinstance(item, ShadowSilentFilter) for item in handler.filters):
            handler.addFilter(silent_filter)
    _filter_attached = True


def get_shadow_silent_mode() -> bool:
    """Return whether the current async context suppresses shadow log output."""
    return _shadow_silent_mode.get()


class ShadowExecutorMiddleware(CodeExecutorMiddleware):
    """Executor middleware that enforces shadow-agent write and execution boundaries."""

    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        raise PermissionError("Python execution is blocked in shadow context.")

    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        raise PermissionError("Bash execution is blocked in shadow context.")

    async def execute_bash_stream(self, context: ExecutionContext) -> AsyncIterator[str]:
        raise PermissionError("Bash execution is blocked in shadow context.")
        yield ""  # pragma: no cover — satisfies async generator typing

    async def write_file(self, path: str, content: str) -> None:
        await self._assert_write_allowed(path)
        await self.inner.write_file(path, content)

    async def write_file_bytes(self, path: str, content: bytes) -> None:
        await self._assert_write_allowed(path)
        await self.inner.write_file_bytes(path, content)

    async def write_file_atomic(self, path: str, content: str) -> None:
        await self._assert_write_allowed(path)
        await self.inner.write_file_atomic(path, content)

    async def write_file_bytes_atomic(self, path: str, content: bytes) -> None:
        await self._assert_write_allowed(path)
        await self.inner.write_file_bytes_atomic(path, content)

    async def append_file(self, path: str, content: str) -> None:
        await self._assert_write_allowed(path)
        await self.inner.append_file(path, content)

    async def delete_file(self, path: str) -> None:
        await self._assert_write_allowed(path)
        await self.inner.delete_file(path)

    async def mkdir(self, path: str) -> None:
        await self._assert_write_allowed(path)
        await self.inner.mkdir(path)

    async def _exec_bash(self, command: str) -> ExecutionResult:
        raise PermissionError("Bash execution is blocked in shadow context.")

    async def _assert_write_allowed(self, path: str) -> None:
        relative = await self._relative_workspace_path(path)
        if relative is None:
            raise PermissionError(f"Write access denied in shadow context: {path}")
        if _is_relative_write_allowed(relative):
            return
        raise PermissionError(
            f"Write access to '{relative}' is blocked in shadow context "
            "(allowed: .context/*, SKILL.md, skill sidecars, references/templates/scripts)."
        )

    async def _relative_workspace_path(self, path: str) -> str | None:
        try:
            resolved = await self.inner.resolve_path(path)
            workspace = Path(self.workspace_path).resolve()
            return Path(resolved).resolve().relative_to(workspace).as_posix()
        except (ValueError, RuntimeError):
            return None


def _is_relative_write_allowed(relative: str) -> bool:
    normalized = relative.removeprefix("./")
    if normalized.startswith(_ALLOWED_CONTEXT_PREFIX):
        return True
    basename = Path(normalized).name
    if basename in _SKILL_ARTIFACT_NAMES:
        return True
    padded = f"/{normalized}/"
    return any(marker in padded for marker in _SKILL_SUPPORT_MARKERS)


@asynccontextmanager
async def restricted_shadow_context(
    *,
    suppress_logs: bool = False,
) -> AsyncGenerator[None]:
    """Apply shadow-agent bulkhead isolation for the current async context.

    Args:
        suppress_logs: When True, shadow-scoped log records are dropped at the root logger.
            Idle-task UI progress events are unaffected (they use the event bus, not logging).
    """
    _ensure_silent_filter()

    executor_token: Token | None = None
    silent_token: Token[bool] | None = None
    shadow_token: Token[bool] | None = None

    original_executor = get_executor()
    if original_executor is not None:
        executor_token = set_executor(ShadowExecutorMiddleware(original_executor))

    shadow_token = set_is_shadow_agent(True)
    if suppress_logs:
        silent_token = _shadow_silent_mode.set(True)

    try:
        yield
    finally:
        if silent_token is not None:
            _shadow_silent_mode.reset(silent_token)
        if shadow_token is not None:
            reset_is_shadow_agent(shadow_token)
        if executor_token is not None:
            reset_executor(executor_token)
