"""Execution interceptor protocol and the hooks that report actions to it.

[INPUT]
- .security.external_effect_detector::detect_external_effects (POS: external-effect classifier for shell commands)
- .security.shell_command_analyzer::is_destructive_command (POS: file-mutating shell command check)

[OUTPUT]
- ExecutionInterceptor: protocol a host implements to react before an action a file rollback cannot fully undo
- set_execution_interceptor / get_execution_interceptor: process-wide interceptor slot
- trigger_destructive_action_hook: timeout-guarded interceptor call
- trigger_bash_action_hook: reports a shell command when it mutates files or has external effects

[POS]
Seam between the code-execution toolkit and a host that wants to snapshot or audit actions.
"""

import asyncio
import logging
from typing import Protocol

from myrm_agent_harness.toolkits.code_execution.security.external_effect_detector import detect_external_effects
from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import is_destructive_command

logger = logging.getLogger(__name__)


class ExecutionInterceptor(Protocol):
    """Protocol for intercepting code execution actions."""

    async def before_destructive_action(self, workspace_path: str, action_type: str, payload: dict) -> None:
        """Called before an action that a file rollback cannot fully undo.

        That is a file mutation (write, delete, ``rm``, ``sed -i``) or a shell command with
        effects outside the workspace (database, container/cloud, network write, publish).

        Args:
            workspace_path: The root path of the workspace.
            action_type: The type of action ('bash', 'file_write', 'file_delete', etc.).
            payload: Additional details about the action. Native file operations carry
                ``path``/``session_id``. ``bash`` also carries ``command``, ``destructive``
                (the command mutates files) and ``external_effects`` (effect categories from
                ``detect_external_effects``; empty when none).
        """
        ...


_interceptor: ExecutionInterceptor | None = None


def set_execution_interceptor(interceptor: ExecutionInterceptor | None) -> None:
    """Set the global execution interceptor."""
    global _interceptor
    _interceptor = interceptor


def get_execution_interceptor() -> ExecutionInterceptor | None:
    """Get the global execution interceptor."""
    return _interceptor


async def trigger_destructive_action_hook(workspace_path: str, action_type: str, payload: dict) -> None:
    """Safely trigger the interceptor with a timeout, ensuring it never blocks execution."""
    interceptor = get_execution_interceptor()
    if not interceptor:
        return

    try:
        # 3 second timeout to ensure we never block the main execution flow
        await asyncio.wait_for(interceptor.before_destructive_action(workspace_path, action_type, payload), timeout=3.0)
    except TimeoutError:
        logger.warning(f"ExecutionInterceptor timeout after 3.0s for {action_type}")
    except Exception as e:
        logger.warning(f"ExecutionInterceptor failed for {action_type}: {e}")


async def trigger_bash_action_hook(workspace_path: str, command: str, session_id: str | None) -> None:
    """Report a shell command to the interceptor when it mutates files or has external effects.

    The interceptor decides what each of the two calls for; a command that is neither is not reported.
    """
    destructive = is_destructive_command(command)
    external_effects = detect_external_effects(command)
    if not destructive and not external_effects:
        return

    await trigger_destructive_action_hook(
        workspace_path=workspace_path,
        action_type="bash",
        payload={
            "command": command,
            "session_id": session_id,
            "destructive": destructive,
            "external_effects": external_effects,
        },
    )
