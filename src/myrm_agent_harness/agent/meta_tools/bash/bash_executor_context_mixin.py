"""BashExecutor execution-context builders and post-run helpers.

[INPUT]
- toolkits.code_execution::ExecutionContext (POS: Code executor protocol and context)
- ._event_logging::log_bash_command_execution (POS: Event logging with redaction)
- agent.artifacts.registry::register_generated_files (POS: Artifact registration)

[OUTPUT]
- BashExecutorContextMixin: _build_execution_context, logging, artifact registration

[POS]
ExecutionContext assembly, OAuth issuer scoping, and post-run logging for BashExecutor.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_execution import ExecutionContext

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution import Workspace
    from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionResult
    from myrm_agent_harness.toolkits.code_execution.executors.models import MCPConfigItem

logger = logging.getLogger(__name__)


class BashExecutorContextMixin:
    """Build ExecutionContext and handle logging / artifact registration."""

    def _resolve_allowed_credential_issuers(self, skill_names: list[str] | None) -> list[str] | None:
        """Scope OAuth injection: all issuers for generic bash; filtered when a skill is active."""
        if not skill_names:
            return None

        if not self._skill_oauth_issuers:
            return []

        issuers: list[str] = []
        for skill_name in skill_names:
            issuer = self._skill_oauth_issuers.get(skill_name)
            if issuer:
                issuers.append(issuer)
        return issuers

    def _build_execution_context(
        self,
        prepared_code: str,
        original_code: str,
        mcp_config_items: list[MCPConfigItem] | None,
        session_id: str | None,
        workspace: Workspace | None,
        env_paths: list[str] | None,
        working_dir: str | None,
        skill_names: list[str] | None = None,
        skill_env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ExecutionContext:
        """Build ExecutionContext from prepared code, workspace, and skill config."""
        network_config = self.config.network

        executor_workspace = getattr(self._executor, "workspace_path", None)
        workspace_root = (
            str(executor_workspace) if executor_workspace else self._workspace_manager.get_workspace_path(workspace)
        )

        work_dir = working_dir if working_dir else "/workspace"

        env: dict[str, str] | None = None
        if env_paths:
            pythonpath = os.pathsep.join(env_paths)
            env = {"PYTHONPATH": pythonpath}

        if self._global_env:
            if env is None:
                env = {}
            env.update(self._global_env)

        if skill_env:
            if env is None:
                env = {}
            env.update(skill_env)

        return ExecutionContext(
            code=prepared_code,
            original_code=original_code,
            session_id=session_id,
            work_dir=work_dir,
            workspace_root=workspace_root,
            active_skills=skill_names,
            allowed_credential_issuers=self._resolve_allowed_credential_issuers(skill_names),
            timeout=timeout if timeout is not None else self._get_timeout(),
            env=env,
            allow_network=network_config.allow_network,
            allowed_hosts=network_config.get_effective_allowed_hosts(),
            mcp_config=mcp_config_items,
        )

    def _get_timeout(self) -> int:
        """Get execution timeout in seconds."""
        return self.config.local.max_execution_time

    def _register_generated_files(self, result: ExecutionResult) -> None:
        """Register generated artifact files from execution result."""
        from myrm_agent_harness.agent.artifacts.registry import register_generated_files

        register_generated_files(generated_files=result.generated_files, container_id=result.container_id)

    def _build_error_details(self, result: ExecutionResult) -> str:
        """Build error detail string from execution result (error > stdout > stderr)."""
        if result.error:
            return result.error
        if result.stdout:
            return result.stdout
        if result.stderr:
            return result.stderr
        return "Unknown error"

    async def _log_bash_command_execution(
        self,
        command: str,
        session_id: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_ms: int,
        success: bool,
        error_message: str = "",
    ) -> None:
        """Delegate to module-level event logging (failure-safe)."""
        from myrm_agent_harness.agent.meta_tools.bash._event_logging import (
            log_bash_command_execution,
        )

        await log_bash_command_execution(
            command=command,
            session_id=session_id,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
        )
