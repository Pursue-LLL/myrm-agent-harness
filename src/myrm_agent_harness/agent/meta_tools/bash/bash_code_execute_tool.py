"""Bash code execution tool (aggregate root).

[INPUT]
- ._tool.tool_description::TOOL_DESCRIPTION (POS: Static LLM-facing description prompt)
- ._security.preflight_checks (POS: Security preflight checks)
- ._executor.executor::BashExecutor (POS: Bash executor aggregate root. MRO: Execute → Background → Prepare → Context)
- ._executor.error::BashExecutionError (POS: Shared error type for BashExecutor mixins and bash_code_execute_tool error surfacing)
- ._tool.helpers (POS: BashInput, OS hint, context tracking)
- ._tool.formatting (POS: Output formatting and truncation)
- ._tool.background_listeners (POS: Background ptc_notify listeners)
- ._tool.multimodal (POS: Vision ContentBlock return path)
- ._tool.exit_semantics (POS: Exit-code semantic interpretation)
- .._context_recovery::ensure_executor, restore_context_vars (POS: Executor ContextVar recovery)

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

from langchain_core.runnables import RunnableConfig
from langchain_core.tools.convert import tool

from myrm_agent_harness.agent.context_management.context import (
    extract_context_from_runnable_config,
)
from myrm_agent_harness.agent.meta_tools._context_recovery import (
    ensure_executor,
    restore_context_vars,
)
from myrm_agent_harness.agent.meta_tools.bash._background.registry import (
    get_background_registry,
)
from myrm_agent_harness.agent.meta_tools.bash._executor.auto_yield import (
    build_auto_yield_return,
    resolve_yield_seconds,
    should_auto_yield,
    wait_for_yield_window,
)
from myrm_agent_harness.agent.meta_tools.bash._security.preflight_checks import (
    check_command_url_exfiltration,
    check_install_packages,
    check_interactive_command,
    check_myrm_tools_import,
    check_sensitive_paths,
    check_unquoted_background_ampersand,
)
from myrm_agent_harness.agent.meta_tools.bash._tool.background_listeners import (
    build_background_listeners,
    classify_background_exit,
)
from myrm_agent_harness.agent.meta_tools.bash._tool.exit_semantics import (
    interpret_exit_code,
)
from myrm_agent_harness.agent.meta_tools.bash._tool.formatting import (
    format_result,
    truncate_bash_output,
)
from myrm_agent_harness.agent.meta_tools.bash._tool.helpers import (
    CONTEXT_PATH_PATTERNS,
    BashInput,
    get_os_hint,
    track_context_access_in_command,
)
from myrm_agent_harness.agent.meta_tools.bash._tool.multimodal import (
    MAX_IMAGES_PER_RETURN,
    maybe_build_image_blocks,
)
from myrm_agent_harness.agent.meta_tools.bash._tool.tool_description import (
    resolve_bash_code_execute_tool_description,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

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


def _coerce_optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def create_bash_code_execute_tool(
    skills: list[SkillMetadata] | None = None,
    *,
    skill_env_map: dict[str, dict[str, str]] | None = None,
    global_env: dict[str, str] | None = None,
    locale: str | None = None,
) -> BaseTool:
    """Create the bash code execution LangChain tool."""

    skill_paths = [s.storage_path for s in (skills or []) if s.storage_path]
    skill_oauth_issuers = {
        s.name: s.oauth_issuer for s in (skills or []) if s.oauth_issuer and s.name
    }

    description = resolve_bash_code_execute_tool_description(locale) + get_os_hint(locale=locale)

    @tool("bash_code_execute_tool", description=description, args_schema=BashInput)
    async def bash_func(
        reason: str,
        command: str,
        timeout: int | None = None,
        run_in_background: bool = False,
        yield_after_seconds: int | None = None,
        *,
        config: RunnableConfig,
    ) -> dict[str, object] | Sequence[object]:
        """Execute a bash command, python script, or skill invocation."""
        intent = reason.strip()
        command = command.strip()
        preview = command[:200] + ("..." if len(command) > 200 else "")
        logger.info("BASH_EXECUTE intent=%r command_preview=%r", intent, preview)

        if ".context/" in command:
            paths = []
            for pattern in CONTEXT_PATH_PATTERNS:
                paths.extend(pattern.findall(command))

            for path in set(paths):
                if path:
                    logger.info("CONTEXT_ACCESS path=%s method=bash_command", path)

        try:
            context = extract_context_from_runnable_config(config)
            workspace_root = str(context.get("workspace_root", "")) or None

            check_command_url_exfiltration(command)
            check_sensitive_paths(command)
            check_myrm_tools_import(command, workspace_root=workspace_root)

            interactive_msg = check_interactive_command(command)
            if interactive_msg is not None and not run_in_background:
                from myrm_agent_harness.utils.errors import ToolError

                raise ToolError(
                    message=interactive_msg,
                    user_hint=interactive_msg,
                    diagnostic_info={"interactive_required": True},
                )

            if not run_in_background:
                bg_amp_msg = check_unquoted_background_ampersand(command)
                if bg_amp_msg is not None:
                    from myrm_agent_harness.utils.errors import ToolError

                    raise ToolError(
                        message=bg_amp_msg,
                        user_hint="Use run_in_background=True for background jobs, or '&&' for chained commands.",
                        diagnostic_info={"detached_background_prohibited": True},
                    )

            await check_install_packages(command)

            session_id = str(context.get("session_id", "")) or None

            from myrm_agent_harness.agent.meta_tools.bash._executor.executor import (
                BashExecutor,
            )
            from myrm_agent_harness.agent.skills.mcp.notify_registry import (
                session_scope,
            )

            executor = ensure_executor(config)
            restore_context_vars(context, executor)
            bash_executor = BashExecutor(executor=executor)
            if skill_oauth_issuers:
                bash_executor.set_skill_oauth_issuers(skill_oauth_issuers)
            if skill_env_map:
                bash_executor.set_skill_env_map(skill_env_map)
            if global_env:
                bash_executor.set_global_env(global_env)

            auto_yield = should_auto_yield(
                command=command,
                run_in_background=run_in_background,
                yield_after_seconds=yield_after_seconds,
            )
            if run_in_background or auto_yield:
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
                from myrm_agent_harness.agent.meta_tools.bash._background.session_spawn_lifecycle import (
                    activate_session_spawn_tool,
                )
                from myrm_agent_harness.agent.meta_tools.bash.bash_process_tools import (
                    BASH_PROCESS_TOOL_NAME,
                )

                activate_session_spawn_tool(session_id, BASH_PROCESS_TOOL_NAME)
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

                if auto_yield and not run_in_background:
                    yield_seconds = resolve_yield_seconds(yield_after_seconds)
                    assert yield_seconds is not None
                    final_info = await wait_for_yield_window(
                        get_background_registry(),
                        info.pid,
                        yield_seconds=yield_seconds,
                    )
                    if final_info is not None:
                        return build_auto_yield_return(
                            info=final_info,
                            yield_seconds=yield_seconds,
                        )

                return {
                    "content": (
                        f"Background process started.\n"
                        f"  job_id: {info.job_id}\n"
                        f"  pid: {info.pid}\n"
                        f"  command: {info.command}\n"
                        f"  status: {info.status}\n\n"
                        "Use bash_process_tool(action='output', pid=...) to poll stdout/stderr, "
                        "bash_process_tool(action='submit_stdin', pid=..., data=...) for interactive "
                        "prompts, or bash_process_tool(action='kill', pid=...) to stop it. "
                        "GUI users can also send input from the Activity panel."
                    ),
                    "metadata": {
                        "background": True,
                        "job_id": info.job_id,
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

            office_warnings = result.get("office_warnings")
            if isinstance(office_warnings, list) and office_warnings:
                warning_lines = "\n".join(
                    f"Office: {item}"
                    for item in office_warnings
                    if isinstance(item, str)
                )
                if warning_lines:
                    formatted_content = f"{formatted_content}\n\n{warning_lines}"

            if is_truncated:
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                await dispatch_custom_event(
                    "agent_status",
                    {"event": "tool_truncated", "tool": "bash", "metadata": trunc_meta},
                    config=config,
                )

            evicted_ref = result.get("evicted_ref")
            if evicted_ref and isinstance(evicted_ref, str):
                from myrm_agent_harness.agent.context_management.infra.evicted import (
                    emit_evicted_ref,
                )

                preview_stdout = (
                    formatted_content if isinstance(formatted_content, str) else None
                )
                await emit_evicted_ref(
                    evicted_ref,
                    tool_name="bash_code_execute_tool",
                    preview_stdout=preview_stdout,
                    stored_chars=_coerce_optional_int(
                        result.get("evicted_stored_chars")
                    ),
                    total_lines=_coerce_optional_int(result.get("evicted_total_lines")),
                    storage_truncated=bool(result.get("evicted_storage_truncated")),
                    stream="stdout",
                    config=config,
                )

            stderr_evicted_ref = result.get("stderr_evicted_ref")
            if stderr_evicted_ref and isinstance(stderr_evicted_ref, str):
                from myrm_agent_harness.agent.context_management.infra.evicted import (
                    emit_evicted_ref,
                )

                await emit_evicted_ref(
                    stderr_evicted_ref,
                    tool_name="bash_code_execute_tool",
                    stored_chars=_coerce_optional_int(
                        result.get("stderr_evicted_stored_chars")
                    ),
                    total_lines=_coerce_optional_int(
                        result.get("stderr_evicted_total_lines")
                    ),
                    storage_truncated=bool(
                        result.get("stderr_evicted_storage_truncated")
                    ),
                    stream="stderr",
                    config=config,
                )

            metadata: dict[str, object] = {}
            if result.get("mcp_metadata") and isinstance(result["mcp_metadata"], dict):
                metadata = result["mcp_metadata"]

            generated = result.get("generated_files")
            generated_files: list[str] = (
                list(generated) if isinstance(generated, list) else []
            )
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
            from myrm_agent_harness.agent.meta_tools.bash._executor.executor import (
                BashExecutionError,
            )
            from myrm_agent_harness.utils.errors import ToolError

            if isinstance(e, ToolError):
                raise

            hint: str | None = None
            diagnostic: dict[str, object] | None = None

            if isinstance(e, BashExecutionError):
                hint = e.error_hint
                if e.error_category:
                    diagnostic = {"error_category": e.error_category}

                if e.stdout_evicted_ref or e.stderr_evicted_ref:
                    from myrm_agent_harness.agent.context_management.infra.evicted import (
                        emit_evicted_ref,
                    )

                    async def _emit_evicted(
                        ref: str,
                        *,
                        stream: str,
                        stored_chars: int | None,
                        total_lines: int | None,
                        storage_truncated: bool,
                    ) -> None:
                        try:
                            await emit_evicted_ref(
                                ref,
                                tool_name="bash_code_execute_tool",
                                stored_chars=stored_chars,
                                total_lines=total_lines,
                                storage_truncated=storage_truncated,
                                stream=stream,
                                config=config,
                            )
                        except Exception as emit_exc:
                            logger.warning(
                                "Failed to emit %s evicted ref %s: %s",
                                stream,
                                ref,
                                emit_exc,
                            )

                    # Failure path intentionally omits preview_stdout: step.stdout
                    # keeps the partial output accumulated during execution (the
                    # "how far did it get" context), while the drawer still exposes
                    # the full evicted stream for read-back.
                    if e.stdout_evicted_ref:
                        await _emit_evicted(
                            e.stdout_evicted_ref,
                            stream="stdout",
                            stored_chars=e.stdout_evicted_stored_chars,
                            total_lines=e.stdout_evicted_total_lines,
                            storage_truncated=e.stdout_evicted_storage_truncated,
                        )
                    if e.stderr_evicted_ref:
                        await _emit_evicted(
                            e.stderr_evicted_ref,
                            stream="stderr",
                            stored_chars=e.stderr_evicted_stored_chars,
                            total_lines=e.stderr_evicted_total_lines,
                            storage_truncated=e.stderr_evicted_storage_truncated,
                        )

                from myrm_agent_harness.agent.meta_tools.bash._tool.terminal_hints import (
                    annotate_failure,
                )

                error_text = f"{e}\n{getattr(e, 'stderr', '')}\n{getattr(e, 'stdout', '')}"
                auto_hint = annotate_failure(command, getattr(e, "exit_code", 1), error_text)
                if auto_hint:
                    hint = f"{hint}\n\n[Diagnostic Hint] {auto_hint}" if hint else f"[Diagnostic Hint] {auto_hint}"

            raise ToolError(
                message=str(e),
                user_hint=hint or "Please fix the code and try again.",
                diagnostic_info=diagnostic,
            ) from e

    return bash_func


__all__ = [
    "MAX_IMAGES_PER_RETURN",
    "BashInput",
    "_build_background_listeners",
    "_classify_background_exit",
    "_format_result",
    "_get_os_hint",
    "_interpret_exit_code",
    "_maybe_build_image_blocks",
    "_restore_context_vars",
    "_track_context_access_in_command",
    "_truncate_bash_output",
    "create_bash_code_execute_tool",
]
