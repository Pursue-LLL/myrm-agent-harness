"""BashExecutor synchronous execute() orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

from myrm_agent_harness.agent.artifacts.file_id_registry import resolve_file_ids_in_text
from myrm_agent_harness.agent.meta_tools.bash.bash_execution_error import BashExecutionError

logger = logging.getLogger(__name__)


class BashExecutorExecuteMixin:
    """Primary synchronous code execution entry point."""

    async def execute(
        self,
        command: str,
        session_id: str | None = None,
        skill_paths: list[str] | None = None,
        timeout: int | None = None,
    ) -> dict[str, object]:
        """Execute a command (Bash or Python) through the injected CodeExecutor."""
        command = resolve_file_ids_in_text(command)

        from myrm_agent_harness.utils.text_utils import unwrap_markdown_fence

        unwrapped = unwrap_markdown_fence(command)
        if unwrapped is not command:
            logger.warning("Stripped Markdown fence from command input")
            command = unwrapped
        if not session_id:
            raise BashExecutionError(
                "session_id is required for code execution. "
                "Business layer must provide session_id in context (e.g., session_id = f'{user_id}_{chat_id}')",
                phase="validation",
                command=command,
                error_category="MISSING_SESSION_ID",
                error_hint="Provide session_id in execute() call",
            )

        executor = self._executor
        logger.info(f" Using executor: {executor.get_executor_name()}")

        workspace, invalidated_workspace_id = await self._workspace_manager.get_or_create(session_id)
        if invalidated_workspace_id:
            self._skill_manager.clear_workspace_cache(invalidated_workspace_id)

        await self._ensure_mcp_proxy_started()

        workspace_root_str = self._workspace_manager.get_workspace_path(workspace)

        use_python_execution, prepared_code, mcp_config_items = self._prepare_execution(
            command,
            session_id=session_id,
            workspace_root=workspace_root_str,
        )

        if not use_python_execution:
            from myrm_agent_harness.toolkits.code_execution.security.archive_sanitizer import sanitize_archive_command

            prepared_code = sanitize_archive_command(prepared_code)
            prepared_code = self._inject_resilience_script(prepared_code)

        detected_skill_name = self._detect_skill_from_code(prepared_code)

        workspace_skill_paths: list[str] = []
        used_skill_paths: list[str] = []

        if workspace and skill_paths and detected_skill_name:
            for skill_path in skill_paths:
                if Path(skill_path).name == detected_skill_name:
                    used_skill_paths.append(skill_path)
                    break

            if used_skill_paths:
                workspace_skill_paths = await self._skill_manager.ensure_skills_in_workspace(
                    workspace, used_skill_paths
                )
                logger.warning(f" Copying detected skill only: {detected_skill_name}")

        if workspace_skill_paths:
            prepared_code, detected_skill_name = self._rewrite_skill_paths(prepared_code, workspace_skill_paths)

        skill_names: list[str] = [detected_skill_name] if detected_skill_name else []

        env_paths: list[str] = []
        working_dir: str | None = None

        if workspace_skill_paths and workspace:
            env_paths = self._convert_to_container_paths(workspace_skill_paths, workspace)
            if detected_skill_name:
                working_dir = f"/workspace/.claude/skills/{detected_skill_name}"

        resolved_skill_env: dict[str, str] | None = None
        if detected_skill_name and self._skill_env_map:
            resolved_skill_env = self._skill_env_map.get(detected_skill_name)

        timeout = self._maybe_extend_timeout_for_mcp(mcp_config_items, timeout)

        context = self._build_execution_context(
            prepared_code=prepared_code,
            original_code=command,
            mcp_config_items=mcp_config_items,
            session_id=session_id,
            workspace=workspace,
            env_paths=env_paths,
            working_dir=working_dir,
            skill_names=skill_names if skill_names else None,
            skill_env=resolved_skill_env,
            timeout=timeout,
        )

        if use_python_execution:
            result = await self._execute_python_with_ptc(context, executor, mcp_config_items is not None)
        else:
            result = await executor.execute_bash(context)

        await self._workspace_manager.update_workspace_timestamp(workspace)

        if result.generated_files:
            self._register_generated_files(result)

        if not result.success and result.error:
            exit_code_val = result.result if isinstance(result.result, int) else 1
            await self._log_bash_command_execution(
                command=command,
                session_id=session_id,
                exit_code=exit_code_val,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                duration_ms=getattr(result, "duration_ms", 0),
                success=False,
                error_message=result.error or "",
            )
            raise BashExecutionError(
                self._build_error_details(result),
                phase="execution",
                command=command,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                error_hint=result.error_hint,
                error_category=result.error_category,
            )

        if not result.success:
            logger.warning(f" Non-zero exit (Exit Code: {result.result})")
        else:
            logger.info(" Command executed successfully")

        clean_stdout, mcp_metadata = self._metadata_extractor.extract_metadata(result.stdout)

        from myrm_agent_harness.agent.meta_tools.bash._output_eviction import maybe_evict_large_output

        eviction_result = await maybe_evict_large_output(clean_stdout, self._executor)

        exit_code_val = result.result if isinstance(result.result, int) else 0
        await self._log_bash_command_execution(
            command=command,
            session_id=session_id,
            exit_code=exit_code_val,
            stdout=eviction_result.text,
            stderr=result.stderr or "",
            duration_ms=getattr(result, "duration_ms", 0),
            success=True,
        )

        return {
            "stdout": eviction_result.text,
            "stderr": result.stderr,
            "exit_code": str(result.result) if result.result is not None else "0",
            "container_id": result.container_id or "",
            "mcp_metadata": mcp_metadata,
            "workspace_root": context.workspace_root or "",
            "generated_files": list(result.generated_files or []),
            "evicted_ref": eviction_result.evicted_ref,
        }
