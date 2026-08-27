"""Shared helpers for bash_code_execute_tool factory (schema, OS hints, context tracking).

[INPUT]
- runtime.context.file_access_tracker::get_file_access_tracker (POS: Context file access audit)
- toolkits.code_execution.platform::detect_platform (POS: Cross-platform runtime detection)
- toolkits.code_execution.env_probe::get_environment_probe_line (POS: Python toolchain probe)

[OUTPUT]
- BashInput: Pydantic args schema for bash_code_execute_tool
- get_os_hint, track_context_access_in_command

[POS]
Non-factory helpers consumed by bash_code_execute_tool and tests via aggregate re-exports.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field, field_validator

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


def get_os_hint(locale: str | None = None) -> str:
    """Generate OS + toolchain hint for LLM to produce correct commands."""
    from myrm_agent_harness.toolkits.code_execution.env_probe import (
        get_environment_probe_line,
    )
    from myrm_agent_harness.toolkits.code_execution.platform import detect_platform
    from myrm_agent_harness.utils.locale import is_chinese

    plat = detect_platform()
    if is_chinese(locale):
        lines = [f"\n\n## 当前系统\nOS: {plat.prompt_label}, Shell: {plat.shell_hint}"]
        if plat.os_type == "macos":
            lines.append("注意 sed/grep/date/stat/readlink 等命令语法与 Linux GNU 版本不同。")
    else:
        lines = [f"\n\n## Environment\nOS: {plat.prompt_label}, Shell: {plat.shell_hint}"]
        if plat.os_type == "macos":
            lines.append("Note that BSD sed/grep/date/stat/readlink syntax differs from Linux GNU versions.")

    env_line = get_environment_probe_line()
    if env_line:
        lines.append(env_line)

    return "\n".join(lines)


class BashInput(BaseModel):
    """Input schema for the bash code execution tool."""

    reason: str = Field(
        description=(
            "Short intent for this execution (≥10 chars). ALWAYS provide this parameter first — "
            "shown in approval UI and audit logs."
        ),
        max_length=500,
    )
    command: str = Field(description="The shell command or python code to execute")

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: object) -> str:
        text = str(value or "").strip()
        if len(text) < 10:
            raise ValueError("reason must be at least 10 characters explaining why this command runs")
        return text

    timeout: int | None = Field(
        default=None,
        description=(
            "Timeout in seconds for foreground execution, up to 600. "
            "IMPORTANT: the default is 120s. Long-running commands (e.g. "
            "'npm install', 'docker build', 'sleep 300') will be interrupted "
            "if you omit this — always pass an explicit value larger than your "
            "expected runtime. Ignored when run_in_background=True — background "
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
    yield_after_seconds: int | None = Field(
        default=None,
        description=(
            "For build/test whitelist commands only: spawn as background, wait up to N seconds "
            "for partial output, then return pid if still running. Default 10 when omitted; set 0 to disable."
        ),
        ge=0,
        le=120,
    )
