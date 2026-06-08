"""Bash code execution tool (LangChain tool factory).

[INPUT]
_tool_description::TOOL_DESCRIPTION (POS: Static LLM-facing description prompt)
_preflight_checks::check_command_url_exfiltration, check_sensitive_paths, check_interactive_command (POS: Security preflight checks)
bash_executor::BashExecutor, BashExecutionError (POS: Code execution orchestrator)
output_compressor::compress_output (POS: Command-aware semantic output compressor)
executors.base::get_executor, set_executor, require_executor (POS: ContextVar executor accessor with RunnableConfig fallback)
skills.mcp.builtin_registry::get_builtin_tool_registry (POS: PTC builtin registry; renders import-style tool description appended to the prompt)
skills.mcp.notify_registry::session_scope (POS: Session→RunnableConfig publisher for PTC `tools.notify` dispatch)
file_ops.utils.image_reader::read_image_as_content_blocks (POS: Image artifact → LangChain ContentBlock converter)
toolkits.code_execution.platform::detect_platform (POS: Cross-platform runtime detection and shell configuration)
toolkits.code_execution.env_probe::get_environment_probe_line (POS: Python toolchain probe for bash tool description injection)

[OUTPUT]
create_bash_tool: Factory creating the bash_code_execute_tool LangChain Tool.

[POS]
Bash code execution tool. Persistent Bash session, security preflight,
exit code semantic interpretation, output formatting, skill invocation,
multimodal image return for vision-capable LLMs, and PTC notify wiring.
"""

import logging
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from langchain_core.tools.convert import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.context_management.context import (
    extract_context_from_runnable_config,
)
from myrm_agent_harness.agent.meta_tools.bash._preflight_checks import (
    check_command_url_exfiltration,
    check_interactive_command,
    check_sensitive_paths,
)
from myrm_agent_harness.agent.meta_tools.bash._tool_description import TOOL_DESCRIPTION

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools.base import BaseTool

    from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
        BackgroundProcessInfo,
        FinishListener,
        ProgressListener,
    )
    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit code semantic table — maps (command, exit_code) to human-readable notes
# so the model doesn't waste turns investigating non-erroneous exit codes.
# ---------------------------------------------------------------------------

_RE_SHELL_SPLIT = re.compile(r"\s*(?:\|\||&&|[|;])\s*")

_EXIT_CODE_SEMANTICS: dict[str, dict[int, str]] = {
    "grep": {1: "No matches found (not an error)"},
    "egrep": {1: "No matches found (not an error)"},
    "fgrep": {1: "No matches found (not an error)"},
    "rg": {1: "No matches found (not an error)"},
    "ag": {1: "No matches found (not an error)"},
    "ack": {1: "No matches found (not an error)"},
    "diff": {1: "Files differ (expected, not an error)"},
    "colordiff": {1: "Files differ (expected, not an error)"},
    "find": {1: "Some directories were inaccessible (partial results may still be valid)"},
    "test": {1: "Condition evaluated to false (expected, not an error)"},
    "[": {1: "Condition evaluated to false (expected, not an error)"},
    "curl": {
        6: "Could not resolve host",
        7: "Failed to connect to host",
        22: "HTTP response code indicated error (e.g. 404, 500)",
        28: "Operation timed out",
    },
    "pytest": {
        1: "Some tests failed",
        2: "Test execution was interrupted",
        5: "No tests were collected",
    },
    "python": {1: "Script exited with error"},
    "ssh": {255: "Connection failed"},
    "scp": {255: "Connection failed"},
    "which": {1: "Command not found (not an error)"},
    "command": {1: "Command not found (not an error)"},
    "cmp": {1: "Files differ (expected, not an error)"},
}

_SIGNAL_NAMES: dict[int, str] = {
    2: "SIGINT",
    6: "SIGABRT",
    9: "SIGKILL",
    11: "SIGSEGV",
    13: "SIGPIPE",
    15: "SIGTERM",
}

_GIT_EXIT_CODE_SEMANTICS: dict[str, dict[int, str]] = {
    "diff": {1: "Files have differences (not an error)"},
    "grep": {1: "No matches found (not an error)"},
    "log": {1: "No commits matched (not an error)"},
    "stash": {1: "Nothing to stash (not an error)"},
    "branch": {1: "Branch not found or already exists"},
}


def _interpret_exit_code(command: str, exit_code: int) -> str | None:
    """Return a human-readable note when a non-zero exit code is non-erroneous.

    Extracts the last command from pipelines/chains, strips env var prefixes
    and absolute paths, then looks up known semantics. For ``git``, performs
    subcommand-level interpretation (e.g. ``git diff`` vs ``git merge``).

    Returns None when exit_code is 0, or when no known semantics exist.
    """
    if exit_code == 0:
        return None

    segments = _RE_SHELL_SPLIT.split(command)
    last_segment = (segments[-1] if segments else command).strip()

    words = last_segment.split()
    base_cmd = ""
    for w in words:
        if "=" in w and not w.startswith("-"):
            continue
        base_cmd = w.rsplit("/", 1)[-1]
        break

    if not base_cmd:
        return None

    if base_cmd == "git":
        subcmd = ""
        found_git = False
        for w in words:
            if "=" in w and not w.startswith("-"):
                continue
            if not found_git:
                if w.rsplit("/", 1)[-1] == "git":
                    found_git = True
                continue
            if not w.startswith("-"):
                subcmd = w
                break
        sub_semantics = _GIT_EXIT_CODE_SEMANTICS.get(subcmd)
        if sub_semantics and exit_code in sub_semantics:
            return sub_semantics[exit_code]
        return None

    cmd_semantics = _EXIT_CODE_SEMANTICS.get(base_cmd)
    if cmd_semantics and exit_code in cmd_semantics:
        return cmd_semantics[exit_code]

    if exit_code > 128:
        signal_num = exit_code - 128
        signal_name = _SIGNAL_NAMES.get(signal_num)
        if signal_name:
            return f"Process terminated by {signal_name} (signal {signal_num})"

    return None


_CONTEXT_PATH_PATTERNS = [
    re.compile(r'["\']?([^\s"\']*\.context/[^\s"\']+)["\']?'),
    re.compile(r"(/workspace/\.context/[^\s]+)"),
]


async def _track_context_access_in_command(command: str, session_id: str) -> None:
    """Track context file access if command accesses context files.

    Args:
        command: Bash command string
        session_id: Current session ID
    """
    try:
        from myrm_agent_harness.runtime.context.file_access_tracker import (
            get_file_access_tracker,
        )

        context_paths: set[str] = set()

        for pattern in _CONTEXT_PATH_PATTERNS:
            for match in pattern.finditer(command):
                path = match.group(1)
                if "/.context/" in path and path.startswith("/persistent"):
                    context_paths.add(path)

        if context_paths:
            tracker = await get_file_access_tracker()
            for path in context_paths:
                await tracker.record_access(path, session_id=session_id)
    except Exception:
        pass


def _get_os_hint() -> str:
    """Generate OS + toolchain hint for LLM to produce correct commands.

    Combines platform detection (from platform.py) with Python environment
    probe (from env_probe.py) into a compact section appended to tool
    description.
    """
    from myrm_agent_harness.toolkits.code_execution.env_probe import (
        get_environment_probe_line,
    )
    from myrm_agent_harness.toolkits.code_execution.platform import detect_platform

    plat = detect_platform()
    lines = [f"\n\n## 当前系统\nOS: {plat.prompt_label}, Shell: {plat.shell_hint}"]

    if plat.os_type == "macos":
        lines.append("注意 sed/grep/date/stat/readlink 等命令语法与 Linux GNU 版本不同。")

    env_line = get_environment_probe_line()
    if env_line:
        lines.append(env_line)

    return "\n".join(lines)


class BashInput(BaseModel):
    """Input schema for the bash code execution tool."""

    command: str = Field(description="The shell command or python code to execute")
    reason: str = Field(description="The reason for executing the command")
    timeout: int | None = Field(
        default=None,
        description=(
            "Optional timeout in seconds for foreground execution. Increase "
            "for long-running tasks like 'npm install' or 'docker build' "
            "(max 600). Ignored when run_in_background=True — background "
            "jobs run until they exit on their own or bash_process_kill_tool "
            "is invoked."
        ),
        ge=1,
        le=600,
    )
    run_in_background: bool = Field(
        default=False,
        description=(
            "Detach the command as a background process and return immediately "
            "with its PID instead of waiting for completion. Use for dev "
            "servers, watchers, long crawlers, or any job whose stdout you "
            "intend to poll later via bash_process_output_tool. Limit to one "
            "active background job per task unless explicitly needed."
        ),
    )


def _restore_context_vars(context: dict[str, object], executor: object) -> None:
    """Restore ContextVars that may be lost when LangGraph executes tool nodes.

    LangGraph's CompiledGraph.astream() may run tool nodes in a context where
    ContextVars set during setup_workspace are not visible. This function
    re-binds them from the RunnableConfig-propagated merged_context.
    """
    from pathlib import Path

    from myrm_agent_harness.agent.middlewares.approval import set_workspace_root
    from myrm_agent_harness.toolkits.code_execution.executors.base import set_executor
    from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
        _workspace_storage_fs_root,
        bind_workspace_storage_root,
    )

    set_executor(executor)  # type: ignore[arg-type]

    workspace_path = context.get("workspace_path")
    if workspace_path:
        set_workspace_root(str(workspace_path))

    if _workspace_storage_fs_root.get() is None:
        ws_root = context.get("workspaces_storage_root")
        if ws_root:
            bind_workspace_storage_root(Path(str(ws_root)))


def create_bash_tool(
    skills: list["SkillMetadata"] | None = None,
    *,
    skill_env_map: dict[str, dict[str, str]] | None = None,
    global_env: dict[str, str] | None = None,
    ptc_tools: "list[BaseTool] | None" = None,
) -> "BaseTool":
    """Create the bash code execution LangChain tool.

    Args:
        skills: Available skill metadata (extracts storage_path for skill routing).
        skill_env_map: Per-skill resolved env vars (skill_name -> env dict).
        global_env: Global environment variables to inject.
        ptc_tools: Tools exposed to Python scripts via PTC (Programmatic Tool Calling).

    Returns:
        LangChain BaseTool for bash/python/skill execution.
    """

    from langchain_core.runnables import RunnableConfig

    skill_paths = [s.storage_path for s in (skills or []) if s.storage_path]

    from myrm_agent_harness.agent.skills.mcp.builtin_registry import (
        get_builtin_tool_registry,
    )

    ptc_desc = get_builtin_tool_registry().get_ptc_description()
    description = TOOL_DESCRIPTION + _get_os_hint() + ptc_desc

    @tool("bash_code_execute_tool", description=description, args_schema=BashInput)
    async def bash_func(
        command: str,
        reason: str = "",
        timeout: int | None = None,
        run_in_background: bool = False,
        *,
        config: RunnableConfig,
    ) -> dict[str, object] | Sequence[object]:
        """Execute a bash command, python script, or skill invocation.

        Returns:
            Either a ``{"content": str, "metadata": {...}}`` dict (text-only
            outputs) or a ``list[ContentBlock]`` when the command produces
            images and the current LLM supports vision (so the model can
            directly *see* the generated chart/screenshot instead of having to
            call ``file_read_tool`` afterwards).
        """
        _ = reason

        command = command.strip()

        if ".context/" in command:
            paths = []
            for pattern in _CONTEXT_PATH_PATTERNS:
                paths.extend(pattern.findall(command))

            # Deduplicate and log access
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

            # Extract runtime context from LangChain config
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
                    _restore_context_vars(context, executor)
            if executor is None:
                raise RuntimeError(
                    "CodeExecutor not available. Call set_executor() to bind an "
                    "executor to the current async context first."
                )
            bash_executor = BashExecutor(executor=executor, ptc_tools=ptc_tools)
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
                finish_listener, progress_listener = _build_background_listeners(session_id=session_id, config=config)
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

            # Publish RunnableConfig so PTC ``tools.notify`` (running in the
            # IPC handler task) can route events into the same LangGraph stream.
            async with session_scope(session_id, config):
                result = await bash_executor.execute(
                    command,
                    session_id=session_id,
                    skill_paths=skill_paths,
                    timeout=timeout,
                )

            # Surface the (one-shot) ``python -c`` transform hint, if any, as a
            # lightweight ``ptc_notify`` so the LLM observes the auto-rewrite
            # without us mutating its tool-call inputs.
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

            # Track context file access if detected in command
            if session_id:
                await _track_context_access_in_command(command, session_id)

            formatted_content, is_truncated, trunc_meta = _format_result(result, command)

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
                    "tasks_steps",
                    {
                        "step_key": "bash_code_execute_tool_tool",
                        "tool_name": "bash_code_execute_tool",
                        "status": "success",
                        "evicted_ref": evicted_ref,
                    },
                    config=config,
                )

            # Build metadata
            metadata: dict[str, object] = {}
            if result.get("mcp_metadata") and isinstance(result["mcp_metadata"], dict):
                metadata = result["mcp_metadata"]

            # Multimodal: when generated_files include images and the model
            # supports vision, return ContentBlocks so the LLM sees the image
            # directly (no extra file_read_tool roundtrip).
            generated = result.get("generated_files")
            generated_files: list[str] = list(generated) if isinstance(generated, list) else []
            blocks = await _maybe_build_image_blocks(
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

                #  Diagnostic Hint: git clone fallback
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


def _build_background_listeners(
    *, session_id: str, config: "RunnableConfig"
) -> tuple["FinishListener", "ProgressListener"]:
    """Return ``(finish_listener, progress_listener)`` bound to this session/config.

    Both listeners forward into ``ptc_notify`` via :func:`dispatch_custom_event`
    so the frontend ActivityCard receives terminal-state and progress updates
    *without* the LLM having to poll. The category is namespaced by PID so the
    UI can merge events into a single card per background job (mirroring the
    ``ptc_notify:background:<pid>:<phase>`` step key handled in
    ``messageStreamHandler.ts``).
    """
    from myrm_agent_harness.utils.event_utils import dispatch_custom_event

    # Both progress and finish events must share the *same* category so the
    # frontend merges them into a single ActivityCard (mid-job progress bar
    # → final completion state on the same row). Phase information is carried
    # by ``message`` + ``level`` + ``progress``.

    async def _on_progress(info: "BackgroundProcessInfo", payload: dict[str, object]) -> None:
        message = str(payload.get("message", "")) or info.command
        envelope: dict[str, object] = {
            "event": "ptc_notify",
            "level": "info",
            "message": message,
            "category": f"background:{info.pid}",
            "session_id": session_id,
        }
        for key in ("progress", "step_index", "total_steps"):
            if key in payload:
                envelope[key] = payload[key]
        await dispatch_custom_event("ptc_notify", envelope, config=config)

    async def _on_finish(info: "BackgroundProcessInfo") -> None:
        # ``exit_code`` carries diagnosis-grade information that we forfeit
        # if we collapse everything into "warn". 137 is the canonical OOM
        # killer exit, 139 is segfault, negative codes are POSIX signals.
        # Surfacing these as ``error_category`` lets the LLM diagnose the
        # failure in one turn ("OOM, lower batch size") instead of guessing.
        error_category = _classify_background_exit(info)
        if info.status == "killed" or (info.status == "exited" and (info.exit_code or 0) == 0):
            level = "info"
        elif error_category in ("oom_killed", "segfault"):
            level = "alert"
        else:
            level = "warn"
        message = f"Background job pid={info.pid} {info.status}" + (
            f" (exit_code={info.exit_code})" if info.exit_code is not None else ""
        )
        envelope: dict[str, object] = {
            "event": "ptc_notify",
            "level": level,
            "message": message,
            "category": f"background:{info.pid}",
            "progress": 100,
            "session_id": session_id,
        }
        if error_category is not None:
            envelope["error_category"] = error_category
        await dispatch_custom_event("ptc_notify", envelope, config=config)

    return _on_finish, _on_progress


def _classify_background_exit(info: "BackgroundProcessInfo") -> str | None:
    """Map ``BackgroundProcessInfo.exit_code`` to a UI-friendly error category.

    Returns ``None`` for benign outcomes (clean exit or user-initiated kill).
    Mapping:
        * 137 → ``oom_killed`` (SIGKILL via the Linux OOM killer)
        * 139 → ``segfault``   (native crash)
        * 143 → ``signal_terminated`` (SIGTERM upgrade)
        * <0  → ``signal_terminated`` (POSIX returns ``-signo``)
        * any other non-zero → ``nonzero_exit``
    """
    if info.status == "exited" and (info.exit_code or 0) == 0:
        return None
    code = info.exit_code
    if code is None:
        return None
    if code == 137:
        return "oom_killed"
    if code == 139:
        return "segfault"
    if code == 143 or code < 0:
        return "signal_terminated"
    if info.status == "killed":
        # User-initiated kill where the runtime reports a positive shell-style
        # exit code (e.g. 130 for SIGINT). Avoid alarming the user.
        return None
    return "nonzero_exit"


MAX_IMAGES_PER_RETURN: Final[int] = 4


async def _maybe_build_image_blocks(
    text_content: str,
    generated_files: list[str],
    context: Mapping[str, object],
) -> Sequence[object] | None:
    """Return ``[TextBlock, *ImageBlocks]`` when images can be returned multimodally.

    Returns ``None`` to signal the caller should keep the plain text-only
    dict response. Triggers only when:
    1. The command produced image artifacts (``generated_files``).
    2. The active LLM advertises vision capability via ``supports_vision``.
    3. ``image_reader`` successfully reads at least one image into a content
       block (it gracefully degrades to a text placeholder when the image is
       too large; in that case we still keep the placeholder as text only).

    At most ``MAX_IMAGES_PER_RETURN`` images are inlined. Anything beyond is
    appended as a single text summary pointing at the remaining paths so the
    LLM can read them on demand via ``file_read_tool``, keeping the token
    budget bounded even when a single execution produces dozens of charts.
    """
    if not generated_files:
        return None

    image_paths = [p for p in generated_files if _is_image_artifact(p)]
    if not image_paths:
        return None

    supports_vision = bool(context.get("supports_vision", False))
    if not supports_vision:
        return None

    from langchain_core.messages.content import ContentBlock, create_text_block

    from myrm_agent_harness.agent.meta_tools.file_ops.utils.image_reader import (
        read_image_as_content_blocks,
    )
    from myrm_agent_harness.toolkits.code_execution.executors.base import (
        require_executor,
    )

    executor = require_executor()
    blocks: list[ContentBlock] = [create_text_block(text_content)]
    appended_image = False

    inline_paths = image_paths[:MAX_IMAGES_PER_RETURN]
    overflow_paths = image_paths[MAX_IMAGES_PER_RETURN:]

    for image_path in inline_paths:
        try:
            image_result = await read_image_as_content_blocks(image_path, executor, supports_vision=True)
        except Exception as exc:  # FileNotFoundError or executor errors
            logger.warning("bash_tool: failed to inline image %s: %s", image_path, exc)
            continue

        if isinstance(image_result, list):
            blocks.extend(image_result)
            appended_image = True
        elif isinstance(image_result, str):
            blocks.append(create_text_block(image_result))

    if not appended_image:
        return None

    if overflow_paths:
        paths_preview = ", ".join(overflow_paths[:8])
        suffix = "" if len(overflow_paths) <= 8 else f" (+{len(overflow_paths) - 8} more)"
        blocks.append(
            create_text_block(
                f"[bash_code_execute_tool] {len(overflow_paths)} additional image(s) "
                f"omitted from inline preview to keep the token budget bounded. "
                f"Use file_read_tool on demand: {paths_preview}{suffix}"
            )
        )

    return blocks


def _is_image_artifact(path: str) -> bool:
    """Detect image-like generated artifacts (delegates to image_reader)."""
    from myrm_agent_harness.agent.meta_tools.file_ops.utils.image_reader import (
        is_image_path,
    )

    return is_image_path(path)


def _truncate_bash_output(output: str, max_chars: int = 8000) -> tuple[str, bool, dict[str, object]]:
    """Smart middle-truncation for bash output to preserve errors at the end."""
    if len(output) <= max_chars:
        return output, False, {}
    half = max_chars // 2
    head = output[:half]
    tail = output[-half:]
    skipped = len(output) - max_chars

    total_lines = output.count("\n") + 1
    total_mb = len(output.encode("utf-8", errors="ignore")) / (1024 * 1024)

    hint = f"[ SYSTEM WARNING: Output is extremely large ({total_mb:.2f}MB, {total_lines} lines). Middle truncated: {skipped} chars skipped. Redirect to a file with > file.txt, then use file_read_tool to read specific sections.]"

    meta = {
        "type": "bash",
        "total_lines": total_lines,
        "total_mb": round(total_mb, 2),
        "shown_chars": max_chars,
    }

    return f"{head}\n\n...{hint}...\n\n{tail}", True, meta


def _format_result(result: Mapping[str, object], command: str = "") -> tuple[str, bool, dict[str, object]]:
    """Format execution result with exit code semantic annotations.

    Uses <tool_output> tag wrapping to prevent prompt injection.

    Args:
        result: Dict containing stdout, stderr, exit_code.
        command: Original command string for exit code interpretation.

    Returns:
        Tuple of (Formatted result string, was_truncated boolean, metadata dict).
    """
    from myrm_agent_harness.utils.context_format import wrap_with_tool_output_tag

    stdout_raw = str(result.get("stdout", ""))
    exit_code = str(result.get("exit_code", "0"))

    if stdout_raw and command:
        from myrm_agent_harness.agent.meta_tools.bash.output_compressor import (
            compress_output,
        )

        workspace_root = str(result.get("workspace_root") or "") or None
        stdout_raw = compress_output(
            command,
            stdout_raw,
            exit_code=exit_code,
            workspace_root=workspace_root,
        )

    stdout_str, stdout_trunc, stdout_meta = _truncate_bash_output(stdout_raw)
    stderr_str, stderr_trunc, stderr_meta = _truncate_bash_output(str(result.get("stderr", "")))

    output_parts: list[str] = []

    if stdout_str:
        output_parts.append(stdout_str)

    if stderr_str:
        output_parts.append(f"[stderr]\n{stderr_str}")

    if exit_code != "0":
        try:
            code_int = int(exit_code)
        except ValueError:
            code_int = -1
        meaning = _interpret_exit_code(command, code_int) if command else None
        if meaning:
            output_parts.append(f"[exit_code: {exit_code} — {meaning}]")
        else:
            output_parts.append(f"[exit_code: {exit_code}]")

    if not output_parts:
        return "(no output)", False, {}

    formatted = "\n".join(output_parts)

    from myrm_agent_harness.utils.text_utils import sanitize_binary_output, strip_ansi

    formatted = strip_ansi(formatted)
    formatted = sanitize_binary_output(formatted)

    from myrm_agent_harness.agent.security.redact import redact_sensitive_text

    formatted = redact_sensitive_text(formatted)

    is_truncated = stdout_trunc or stderr_trunc
    meta = stdout_meta if stdout_trunc else (stderr_meta if stderr_trunc else {})

    return wrap_with_tool_output_tag(formatted), is_truncated, meta
