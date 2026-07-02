"""Bash code execution tool (aggregate root).

[INPUT]
- ._tool_description::TOOL_DESCRIPTION (POS: Static LLM-facing description prompt)
- ._preflight_checks (POS: Security preflight checks)
- .bash_executor::BashExecutor, BashExecutionError (POS: Code execution orchestrator)
- .bash_tool_helpers (POS: BashInput, context restore, OS hint, context tracking)
- .bash_tool_formatting (POS: Output formatting and truncation)
- .bash_tool_background_listeners (POS: Background ptc_notify listeners)
- .bash_tool_multimodal (POS: Vision ContentBlock return path)
- .bash_tool_exit_semantics (POS: Exit-code semantic interpretation)

[OUTPUT]
- create_bash_code_execute_tool: Factory creating the bash_code_execute_tool LangChain Tool
- Re-exported helpers for tests (see __all__)

[POS]
Bash code execution LangChain tool aggregate root.
Public import path: ``from ...bash_code_execute_tool import create_bash_code_execute_tool``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from langchain_core.tools.convert import tool
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.context_management.context import (
    extract_context_from_runnable_config,
)
from myrm_agent_harness.agent.meta_tools.bash._preflight_checks import (
    check_command_url_exfiltration,
    check_install_packages,
    check_interactive_command,
    check_sensitive_paths,
)
from myrm_agent_harness.agent.meta_tools.bash._tool_description import TOOL_DESCRIPTION
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_background_listeners import (
    build_background_listeners,
    classify_background_exit,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_exit_semantics import interpret_exit_code
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_formatting import (
    format_result,
    truncate_bash_output,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_helpers import (
    CONTEXT_PATH_PATTERNS,
    BashInput,
    get_os_hint,
    restore_context_vars,
    track_context_access_in_command,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_multimodal import (
    MAX_IMAGES_PER_RETURN,
    maybe_build_image_blocks,
)

if TYPE_CHECKING:
    from langchain_core.tools.base import BaseTool

    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)

# Test-oriented re-exports from the bash_code_execute_tool aggregate module.
_interpret_exit_code = interpret_exit_code
_format_result = format_result
_truncate_bash_output = truncate_bash_output
_get_os_hint = get_os_hint
_restore_context_vars = restore_context_vars
_track_context_access_in_command = track_context_access_in_command
_build_background_listeners = build_background_listeners
_classify_background_exit = classify_background_exit
_maybe_build_image_blocks = maybe_build_image_blocks
_CONTEXT_PATH_PATTERNS = CONTEXT_PATH_PATTERNS


def create_bash_code_execute_tool(
    skills: list[SkillMetadata] | None = None,
    *,
    skill_env_map: dict[str, dict[str, str]] | None = None,
    global_env: dict[str, str] | None = None,
    ptc_tools: list[BaseTool] | None = None,
) -> BaseTool:
    """Create the bash code execution LangChain tool."""

    skill_paths = [s.storage_path for s in (skills or []) if s.storage_path]
    skill_oauth_issuers = {
        s.name: s.oauth_issuer
        for s in (skills or [])
        if s.oauth_issuer and s.name
    }

    from myrm_agent_harness.agent.skills.mcp.builtin_registry import (
        get_builtin_tool_registry,
    )

    ptc_desc = get_builtin_tool_registry().get_ptc_description()
    description = TOOL_DESCRIPTION + get_os_hint() + ptc_desc

    @tool("bash_code_execute_tool", description=description, args_schema=BashInput)
    async def bash_func(
        command: str,
        reason: str = "",
        timeout: int | None = None,
        run_in_background: bool = False,
        *,
        config: RunnableConfig,
    ) -> dict[str, object] | Sequence[object]:
        """Execute a bash command, python script, or skill invocation."""
        _ = reason

        command = command.strip()

        if ".context/" in command:
            paths = []
            for pattern in CONTEXT_PATH_PATTERNS:
                paths.extend(pattern.findall(command))

            for path in set(paths):
                if path:
                    logger.info("CONTEXT_ACCESS path=%s method=bash_command", path)

        try:
            check_command_url_exfiltration(command)
            check_sensitive_paths(command)

            interactive_msg = check_interactive_command(command)
            if interactive_msg is not None:
                from myrm_agent_harness.utils.errors import ToolError

                raise ToolError(
                    message=interactive_msg,
                    user_hint=interactive_msg,
                    diagnostic_info={"interactive_required": True},
                )

            await check_install_packages(command)

            context = extract_context_from_runnable_config(config)
            session_id = str(context.get("session_id", "")) or None

            from myrm_agent_harness.agent.meta_tools.bash.bash_executor import (
                BashExecutor,
            )
            from myrm_agent_harness.agent.skills.mcp.notify_registry import (
                session_scope,
            )
            from myrm_agent_harness.toolkits.code_execution.executors.base import (
                get_executor,
                get_stashed_executor,
            )

            executor = get_executor()
            if executor is None and session_id:
                executor = get_stashed_executor(session_id)
                if executor is not None:
                    restore_context_vars(context, executor)
            if executor is None:
                raise RuntimeError(
                    "CodeExecutor not available. Call set_executor() to bind an "
                    "executor to the current async context first."
                )
            bash_executor = BashExecutor(executor=executor, ptc_tools=ptc_tools)
            if skill_oauth_issuers:
                bash_executor.set_skill_oauth_issuers(skill_oauth_issuers)
            if skill_env_map:
                bash_executor.set_skill_env_map(skill_env_map)
            if global_env:
                bash_executor.set_global_env(global_env)

            if run_in_background:
                if not session_id:
                    from myrm_agent_harness.utils.errors import ToolError

                    raise ToolError(
                        message="run_in_background requires a bound session_id.",
                        user_hint="Background jobs are scoped per chat session.",
                    )
                finish_listener, progress_listener = build_background_listeners(
                    session_id=session_id, config=config
                )
                info = await bash_executor.spawn_background(
                    command=command,
                    session_id=session_id,
                    finish_listener=finish_listener,
                    progress_listener=progress_listener,
                )
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                await dispatch_custom_event(
                    "ptc_notify",
                    {
                        "event": "ptc_notify",
                        "level": "info",
                        "message": f"Background job pid={info.pid} started",
                        "category": f"background:{info.pid}:started",
                        "session_id": session_id,
                    },
                    config=config,
                )
                return {
                    "content": (
                        f"Background process started.\n"
                        f"  pid: {info.pid}\n"
                        f"  command: {info.command}\n"
                        f"  status: {info.status}\n\n"
                        "Use bash_process_output_tool(pid) to poll stdout/stderr "
                        "or bash_process_kill_tool(pid) to stop it."
                    ),
                    "metadata": {
                        "background": True,
                        "pid": info.pid,
                        "status": info.status,
                    },
                }

            async with session_scope(session_id, config):
                result = await bash_executor.execute(
                    command,
                    session_id=session_id,
                    skill_paths=skill_paths,
                    timeout=timeout,
                )

            transform_hint = bash_executor.consume_python_c_transform_hint()
            if transform_hint:
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                await dispatch_custom_event(
                    "ptc_notify",
                    {
                        "event": "ptc_notify",
                        "level": "info",
                        "message": transform_hint,
                        "category": "code_rewrite",
                        "session_id": session_id,
                    },
                    config=config,
                )

            if session_id:
                await track_context_access_in_command(command, session_id)

            formatted_content, is_truncated, trunc_meta = format_result(result, command)

            if is_truncated:
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                await dispatch_custom_event(
                    "agent_status",
                    {"event": "tool_truncated", "tool": "bash", "metadata": trunc_meta},
                    config=config,
                )

            evicted_ref = result.get("evicted_ref")
            if evicted_ref and isinstance(evicted_ref, str):
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                await dispatch_custom_event(
                    "tool_evicted_ref",
                    {"evicted_ref": evicted_ref},
                    config=config,
                )

            metadata: dict[str, object] = {}
            if result.get("mcp_metadata") and isinstance(result["mcp_metadata"], dict):
                metadata = result["mcp_metadata"]

            generated = result.get("generated_files")
            generated_files: list[str] = list(generated) if isinstance(generated, list) else []
            blocks = await maybe_build_image_blocks(
                text_content=formatted_content,
                generated_files=generated_files,
                context=context,
            )
            if blocks is not None:
                return blocks

            return {
                "content": formatted_content,
                "metadata": metadata,
            }
        except Exception as e:
            from myrm_agent_harness.agent.meta_tools.bash.bash_executor import (
                BashExecutionError,
            )
            from myrm_agent_harness.utils.errors import ToolError

            hint: str | None = None
            diagnostic: dict[str, object] | None = None

            if isinstance(e, BashExecutionError):
                hint = e.error_hint
                if e.error_category:
                    diagnostic = {"error_category": e.error_category}

                if "git clone" in command and "github.com" in command:
                    git_hint = (
                        "[ Diagnostic Hint] 'git clone' failed or timed out. For large repositories, it is recommended to use curl to download the tarball instead:\n"
                        "curl -sL https://api.github.com/repos/<owner>/<repo>/tarball -o repo.tar.gz && tar -xzf repo.tar.gz"
                    )
                    hint = f"{hint}\n\n{git_hint}" if hint else git_hint

            raise ToolError(
                message=str(e),
                user_hint=hint or "Please fix the code and try again.",
                diagnostic_info=diagnostic,
            ) from e

    return bash_func


__all__ = [
    "MAX_IMAGES_PER_RETURN",
    "BashInput",
    "create_bash_code_execute_tool",
    "_build_background_listeners",
    "_classify_background_exit",
    "_format_result",
    "_get_os_hint",
    "_interpret_exit_code",
    "_maybe_build_image_blocks",
    "_restore_context_vars",
    "_track_context_access_in_command",
    "_truncate_bash_output",
]
