"""BashExecutor MCP proxy, preparation, and skill path helpers.

[INPUT]
- toolkits.code_execution.code_detector::code_detector, CodeType (POS: Code type detector)
- agent.skills.mcp.executor::skill_executor (POS: Skill MCP execution bridge)
- toolkits.code_execution.ptc.context::ptc_nesting_guard (POS: PTC nesting guard)
- .bash_execution_error::BashExecutionError (POS: Structured execution error)
- .bash_executor_constants::MCP_MIN_TIMEOUT (POS: MCP timeout floor)

[OUTPUT]
- BashExecutorPrepareMixin: _prepare_execution, MCP proxy, skill path rewrite, PTC routing

[POS]
Code-type detection, skill staging, MCP IPC startup, and Python PTC injection routing.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.meta_tools.bash.bash_execution_error import BashExecutionError
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_constants import MCP_MIN_TIMEOUT
from myrm_agent_harness.agent.skills.runtime.env import rewrite_skill_paths
from myrm_agent_harness.toolkits.code_execution import ExecutionContext
from myrm_agent_harness.toolkits.code_execution.code_detector import CodeType, code_detector
from myrm_agent_harness.toolkits.code_execution.ptc.context import ptc_nesting_guard
from myrm_agent_harness.toolkits.code_execution.utils import WorkspacePathResolver

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution import Workspace
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor, ExecutionResult
    from myrm_agent_harness.toolkits.code_execution.executors.models import MCPConfigItem

logger = logging.getLogger(__name__)


class BashExecutorPrepareMixin:
    """Detect execution mode and prepare code, MCP proxy, and skill staging helpers."""

    async def _ensure_mcp_proxy_started(self) -> None:
        """Ensure MCP IPC server is started for cross-process communication."""
        if self._mcp_proxy_started:
            return

        executor_mcp_config = self._executor.get_mcp_communication_config()
        if executor_mcp_config and executor_mcp_config.skip_local_proxy:
            logger.warning(
                " [MCP Proxy] Skipping local proxy startup "
                f"(executor '{self._executor.get_executor_name()}' uses direct callback)"
            )
            self._mcp_proxy_started = True
            return

        socket_path = self._get_ipc_socket_path()
        try:
            await self._start_ipc_server(socket_path)
            self._mcp_proxy_started = True
        except Exception as e:
            error_msg = f"Failed to start MCP IPC server at {socket_path}: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def _get_ipc_socket_path(self) -> str:
        """Get IPC socket path from executor config or code execution config."""
        executor_mcp_config = self._executor.get_mcp_communication_config()
        if executor_mcp_config and executor_mcp_config.socket_path:
            return executor_mcp_config.socket_path

        return self.config.mcp_proxy.socket_path

    async def _start_ipc_server(self, socket_path: str) -> None:
        """Start the MCP IPC server if not already running."""
        from myrm_agent_harness.agent.skills.mcp import get_mcp_ipc_server, start_mcp_ipc_server

        if get_mcp_ipc_server() is None:
            await start_mcp_ipc_server(socket_path)
            logger.info(f" [MCP Proxy] Started IPC Server at {socket_path}")

    def _prepare_execution(
        self,
        command: str,
        session_id: str | None = None,
        workspace_root: str | None = None,
    ) -> tuple[bool, str, list[MCPConfigItem] | None]:
        """Detect execution mode (Python/Bash/Skill) and prepare code."""
        use_python_execution = False
        prepared_code = command
        mcp_config_items = None

        if self._enable_skill_execution and self._skill_executor:
            is_skill, skill_name = self._skill_executor.detect_skill_in_command(command)

            if is_skill and skill_name:
                use_python_execution = True
                ipc_socket_path = self._get_ipc_socket_path()
                logger.info(f" [MCP] Using IPC mode (socket: {ipc_socket_path})")

                skill_context = self._skill_executor.prepare_for_execution(
                    command=command,
                    ipc_socket_path=ipc_socket_path,
                    session_id=session_id,
                    workspace_root=workspace_root,
                )
                prepared_code = skill_context.prepared_code
                mcp_config_items = skill_context.mcp_config

        if not use_python_execution:
            detection_result = code_detector.detect(command)
            if detection_result.code_type == CodeType.PYTHON:
                use_python_execution = True
                prepared_code = detection_result.extracted_code
                logger.info(f" Python code detected ({detection_result.detection_reason})")
                if "python" in command and "-c" in command:
                    self._last_python_c_transform_hint = (
                        "Detected `python -c` wrapper — auto-rewrote to file-mode "
                        "execution. Next time pass Python source directly; the "
                        "tool auto-detects code type and avoids shell quoting bugs."
                    )

        if use_python_execution:
            self._validate_python_syntax(prepared_code, command)

        return use_python_execution, prepared_code, mcp_config_items

    def consume_python_c_transform_hint(self) -> str | None:
        """Return + clear the last ``python -c`` transform hint, if any."""
        hint: str | None = getattr(self, "_last_python_c_transform_hint", None)
        self._last_python_c_transform_hint = None  # type: ignore[assignment]
        return hint

    @staticmethod
    def _validate_python_syntax(code: str, original_command: str) -> None:
        """Pre-check extracted Python code via ``ast.parse`` before execution."""
        from myrm_agent_harness.toolkits.code_execution.python_extractor import validate_python_syntax

        error = validate_python_syntax(code)
        if error is None:
            return

        is_python_c = "python" in original_command and "-c" in original_command
        hint = (
            (
                "The python3 -c command produced invalid Python after shell quote processing. "
                "Pass your Python code directly to bash_code_execute_tool WITHOUT the "
                "'python3 -c' wrapper — the tool auto-detects Python."
            )
            if is_python_c
            else (f"Pre-execution syntax check failed: {error}. Fix the code before retrying.")
        )

        raise BashExecutionError(
            f"Python syntax validation failed: {error}",
            phase="preparation",
            command=original_command,
            stdout="",
            stderr=error,
            error_hint=hint,
            error_category="syntax_error",
        )

    async def _execute_python_with_ptc(
        self,
        context: ExecutionContext,
        executor: CodeExecutor,
        is_skill_execution: bool,
    ) -> ExecutionResult:
        """Execute Python with full PTC injection when not nested and not skill mode."""
        if is_skill_execution or ptc_nesting_guard.get() or not self._ptc_tools:
            return await executor.execute(context)

        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            inject_ptc_for_python_execution,
        )

        return await inject_ptc_for_python_execution(context, executor, self._ptc_tools)

    def _inject_resilience_script(self, prepared_code: str) -> str:
        """Prepend the bash resilience init script if available."""
        script_path = Path(__file__).parent / "scripts" / "resilience_init.sh"
        if not script_path.exists():
            return prepared_code
        try:
            resilience_script = script_path.read_text(encoding="utf-8")
            if resilience_script.startswith("#!/bin/bash"):
                resilience_script = resilience_script[len("#!/bin/bash") :].lstrip()
            return f"{resilience_script}\n\n{prepared_code}"
        except Exception as e:
            logger.warning(f"Failed to inject resilience script: {e}")
            return prepared_code

    def _detect_skill_from_code(self, code: str) -> str | None:
        """Detect skill name from Python import patterns or .claude/skills paths."""
        from myrm_agent_harness.agent.skills.runtime.env import detect_skill_script_command

        detected, skill_name = detect_skill_script_command(code)
        if detected and skill_name:
            return skill_name

        match = re.search(r"from\s+skills\.([a-zA-Z0-9_-]+)\s+import", code)
        if match:
            return match.group(1)

        match = re.search(r"import\s+skills\.([a-zA-Z0-9_-]+)", code)
        if match:
            return match.group(1)

        return None

    def _rewrite_skill_paths(self, code: str, workspace_skill_paths: list[str]) -> tuple[str, str | None]:
        """Rewrite skill absolute paths to relative paths in code."""
        rewritten_code, detected_skill = rewrite_skill_paths(code, active_skill_names=None)

        if detected_skill:
            logger.info(f" Path rewrite: .claude/skills/{detected_skill}/ -> relative")
            return rewritten_code, detected_skill

        return code, None

    def _convert_to_container_paths(self, workspace_skill_paths: list[str], workspace: Workspace) -> list[str]:
        """Convert local absolute paths to container paths (/workspace/...)."""
        workspace_root_str = self._workspace_manager.get_workspace_path(workspace)
        if not workspace_root_str:
            logger.warning(" workspace_root is empty, cannot convert paths")
            return []

        return WorkspacePathResolver.to_container_paths(workspace_skill_paths, workspace_root_str)

    def _maybe_extend_timeout_for_mcp(self, mcp_config_items: list[MCPConfigItem] | None, timeout: int | None) -> int | None:
        """Raise timeout floor when MCP skill execution is active."""
        if mcp_config_items and (timeout is None or timeout < MCP_MIN_TIMEOUT):
            logger.warning("Auto-increased timeout %ss -> %ss for MCP skill execution", timeout, MCP_MIN_TIMEOUT)
            return MCP_MIN_TIMEOUT
        return timeout
