"""BashExecutor background process spawn.

[INPUT]
- ._background.registry::get_background_registry, BackgroundQuotaError (POS: Background job registry)
- .error::BashExecutionError (POS: Shared error type for BashExecutor mixins and bash_code_execute_tool error surfacing)
- agent.artifacts.file_id_registry::resolve_file_ids_in_text (POS: File ID resolution)

[OUTPUT]
- BashExecutorBackgroundMixin.spawn_background

[POS]
Long-running shell spawn via background process registry; bypasses skill/python fast path.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.artifacts.file_id_registry import resolve_file_ids_in_text
from myrm_agent_harness.agent.meta_tools.bash._executor.error import (
    BashExecutionError,
)
from myrm_agent_harness.toolkits.code_execution import ExecutionContext

if TYPE_CHECKING:
    from myrm_agent_harness.agent.meta_tools.bash._background.registry import (
        BackgroundProcessInfo,
        FinishListener,
        ProgressListener,
    )

logger = logging.getLogger(__name__)


def strip_trailing_background_ampersand(command: str) -> str:
    """Remove a bare trailing ``&`` so ``sh -c`` cannot orphan the spawned job.

    ``spawn_background`` runs ``sh -c <command>``. A trailing ``&`` makes ``sh``
    return immediately while the real process keeps running detached: the
    registered PID then points at an already-exited shell and every
    ``bash_process_tool`` action (output/kill/wait) silently fails. ``&&`` is a
    chaining operator and is preserved.
    """
    stripped = command.rstrip()
    if stripped.endswith("&") and not stripped.endswith("&&"):
        return stripped[:-1].rstrip()
    return command


class BashExecutorBackgroundMixin:
    """Spawn long-running shell commands via the background process registry."""

    async def spawn_background(
        self,
        command: str,
        session_id: str,
        *,
        finish_listener: FinishListener | None = None,
        progress_listener: ProgressListener | None = None,
    ) -> BackgroundProcessInfo:
        """Spawn a long-running shell command and immediately return its PID."""
        command = resolve_file_ids_in_text(command)
        from myrm_agent_harness.utils.text_utils import unwrap_markdown_fence

        unwrapped = unwrap_markdown_fence(command)
        if unwrapped is not command:
            command = unwrapped

        normalized = strip_trailing_background_ampersand(command)
        if normalized != command:
            logger.warning(
                " [BashExecutor] Background command had a trailing '&' that would orphan "
                "the spawned process; stripped it: %r",
                command,
            )
            command = normalized

        workspace, invalidated_workspace_id = await self._workspace_manager.get_or_create(session_id)
        if invalidated_workspace_id:
            self._skill_manager.clear_workspace_cache(invalidated_workspace_id)

        workspace_root_str = self._workspace_manager.get_workspace_path(workspace)
        if workspace_root_str:
            self._executor.bind_workspace(workspace_root_str)
        workspace_root = workspace_root_str or ""

        network_config = self.config.network

        context = ExecutionContext(
            code="sh",
            args=["-c", command],
            original_code=command,
            session_id=session_id,
            work_dir="/workspace",
            workspace_root=workspace_root,
            active_skills=[],
            env=dict(self._global_env) if self._global_env else None,
            allow_network=network_config.allow_network,
            allowed_hosts=network_config.get_effective_allowed_hosts(),
            mcp_config=None,
        )

        spawn_method = getattr(self._executor, "spawn_background_process", None)
        if spawn_method is None:
            raise BashExecutionError(
                f"Background execution is not supported by the active executor ({self._executor.get_executor_name()}).",
                phase="validation",
                error_category="BACKGROUND_UNSUPPORTED",
                error_hint="Use a LocalExecutor backend or omit run_in_background.",
            )

        proc = await spawn_method(context)

        from myrm_agent_harness.agent.meta_tools.bash._background.registry import (
            BackgroundQuotaError,
            get_background_registry,
        )

        registry = get_background_registry()
        try:
            info = await registry.register(
                proc,
                command=command,
                session_id=session_id,
                finish_listener=finish_listener,
                progress_listener=progress_listener,
            )
        except BackgroundQuotaError as exc:
            with suppress(ProcessLookupError, OSError):
                proc.kill()
            raise BashExecutionError(
                str(exc),
                phase="validation",
                error_category="BACKGROUND_QUOTA_EXCEEDED",
                error_hint=("Stop or wait for an existing background job before starting a new one."),
            ) from exc

        await self._log_bash_command_execution(
            command=command,
            session_id=session_id,
            exit_code=0,
            stdout=f"[background_spawn] pid={info.pid}",
            stderr="",
            duration_ms=0,
            success=True,
        )
        return info
