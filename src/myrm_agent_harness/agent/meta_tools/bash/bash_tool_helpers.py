"""Shared helpers for bash_code_execute_tool factory (schema, context restore, OS hints).

[INPUT]
- runtime.context.file_access_tracker::get_file_access_tracker (POS: Context file access audit)
- toolkits.code_execution.platform::detect_platform (POS: Cross-platform runtime detection)
- toolkits.code_execution.env_probe::get_environment_probe_line (POS: Python toolchain probe)

[OUTPUT]
- BashInput: Pydantic args schema for bash_code_execute_tool
- restore_context_vars, get_os_hint, track_context_access_in_command

[POS]
Non-factory helpers consumed by bash_code_execute_tool and tests via aggregate re-exports.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

CONTEXT_PATH_PATTERNS = [
    re.compile(r'["\']?([^\s"\']*\.context/[^\s"\']+)["\']?'),
    re.compile(r"(/workspace/\.context/[^\s]+)"),
]


async def track_context_access_in_command(command: str, session_id: str) -> None:
    """Track context file access if command accesses context files."""
    try:
        from myrm_agent_harness.runtime.context.file_access_tracker import (
            get_file_access_tracker,
        )

        context_paths: set[str] = set()

        for pattern in CONTEXT_PATH_PATTERNS:
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


def get_os_hint() -> str:
    """Generate OS + toolchain hint for LLM to produce correct commands."""
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
            "jobs run until they exit on their own or bash_process_tool(action='kill') "
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
            "intend to poll later via bash_process_tool(action='output'). Limit to one "
            "active background job per task unless explicitly needed."
        ),
    )


def restore_context_vars(context: dict[str, object], executor: object) -> None:
    """Restore ContextVars that may be lost when LangGraph executes tool nodes."""
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
