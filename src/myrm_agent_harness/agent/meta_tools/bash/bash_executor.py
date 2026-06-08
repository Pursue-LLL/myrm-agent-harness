"""Bash code execution orchestrator (DI-based).

[INPUT]
code_detector::code_detector, CodeType (POS: Code type detector)
mcp_citation_handler::MCPMetadataExtractor (POS: MCP citation handler)
skill_workspace_manager::SkillWorkspaceManager (POS: Skill workspace manager)
workspace_manager::WorkspaceManager (POS: Workspace manager)
toolkits.code_execution::CodeExecutor, ExecutionContext (POS: Code executor protocol and context)
artifacts.file_id_registry::resolve_file_ids_in_text (POS: File ID resolution)
_event_logging::log_bash_command_execution (POS: Event logging with redaction)
_background_registry::get_background_registry, BackgroundQuotaError (POS: Background process registry)

[OUTPUT]
BashExecutor: Code execution orchestrator. Synchronous ``execute()`` for Bash/Python/Skill
routing, asynchronous ``spawn_background()`` for detached long-running jobs.
BashExecutionError: Execution error with error_hint + error_category diagnostics.

[POS]
Bash executor. Provides code execution supporting Bash commands, Python scripts,
and skill invocations via CodeExecutor protocol for environment decoupling.
"""

import logging
import os
from contextlib import suppress
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
        BackgroundProcessInfo,
        FinishListener,
        ProgressListener,
    )
    from myrm_agent_harness.toolkits.code_execution import Workspace
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor, ExecutionResult

from myrm_agent_harness.agent.artifacts.file_id_registry import resolve_file_ids_in_text
from myrm_agent_harness.agent.meta_tools.bash.code_detector import CodeType, code_detector
from myrm_agent_harness.agent.meta_tools.bash.mcp_citation_handler import MCPMetadataExtractor
from myrm_agent_harness.agent.meta_tools.bash.skill_workspace_manager import SkillWorkspaceManager
from myrm_agent_harness.agent.meta_tools.bash.workspace_manager import WorkspaceManager
from myrm_agent_harness.agent.skills.runtime.env import rewrite_skill_paths
from myrm_agent_harness.toolkits.code_execution import ExecutionConfig, ExecutionContext
from myrm_agent_harness.toolkits.code_execution.executors.models import MCPConfigItem
from myrm_agent_harness.toolkits.code_execution.utils import WorkspacePathResolver

logger = logging.getLogger(__name__)

# Prevents nested PTC injection when a PTC script calls myrm_tools.bash()
# with Python code — the inner execution skips PTC server startup.
_in_ptc_context: ContextVar[bool] = ContextVar("_in_ptc_context", default=False)

# MCP tool calls involve IPC + network round-trips; bash must not kill the
# process before the IPC client (TOTAL_TIMEOUT=90s) has a chance to finish.
_MCP_MIN_TIMEOUT = 120


class BashExecutionError(Exception):
    """Bash execution error with structured diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        error_hint: str | None = None,
        error_category: str | None = None,
        phase: str | None = None,
        command: str = "",
        stdout: str = "",
        stderr: str = "",
    ):
        super().__init__(message)
        self.error_hint = error_hint
        self.error_category = error_category
        self.phase = phase
        self.command = command
        self.stdout_preview = self._smart_truncate(stdout, 160)
        self.stderr_preview = self._smart_truncate(stderr, 160)

    @staticmethod
    def _smart_truncate(text: str, limit: int) -> str:
        """Smart truncation: preserve head + tail."""
        if not text:
            return "(empty)"
        if len(text) <= limit:
            return text
        half = limit // 2
        head = text[:half]
        tail = text[-half:]
        omitted = len(text) - limit
        return f"{head}... ({omitted} chars omitted) ...{tail}"

    def format_diagnostic(self) -> str:
        """Generate structured diagnostic report."""
        if not self.phase:
            return str(self)

        lines = [
            "Bash Execution Error",
            "=" * 50,
            f"Phase:    {self.phase}",
            f"Category: {self.error_category or 'UNKNOWN'}",
            f"Command:  {self.command}",
            "",
            "Stdout Preview:",
            f" {self.stdout_preview}",
            "",
            "Stderr Preview:",
            f" {self.stderr_preview}",
        ]

        if self.error_hint:
            lines.extend(["", f"Hint: {self.error_hint}"])

        lines.append("=" * 50)
        return "\n".join(lines)


class BashExecutor:
    """Code execution orchestrator (DI-based, stateless per call).

    Accepts an injected CodeExecutor for the actual process execution.
    Handles business logic: code type detection, MCP skill preparation,
    workspace management, and event logging.
    """

    def __init__(
        self,
        executor: "CodeExecutor",
        enable_skill_execution: bool = True,
        ptc_tools: "list[BaseTool] | None" = None,
    ) -> None:
        self._executor = executor
        self._enable_skill_execution = enable_skill_execution
        self._ptc_tools: list[BaseTool] = ptc_tools or []
        self._skill_executor = None
        self._mcp_proxy_started = False

        self._workspace_manager = WorkspaceManager()
        self._skill_manager = SkillWorkspaceManager()
        self._metadata_extractor = MCPMetadataExtractor()

        self._skill_env_map: dict[str, dict[str, str]] | None = None
        self._global_env: dict[str, str] | None = None

        # Lazy-init skill executor
        if enable_skill_execution:
            from myrm_agent_harness.agent.skills.mcp.executor import skill_executor

            self._skill_executor = skill_executor

    @property
    def config(self) -> ExecutionConfig:
        """Execution config from the underlying CodeExecutor."""
        if self._executor.config is None:
            raise RuntimeError("CodeExecutor config is None")
        return self._executor.config

    def set_skill_env_map(self, env_map: dict[str, dict[str, str]]) -> None:
        """Set per-skill resolved env vars for injection during execution.

        Args:
            env_map: Mapping of skill_name -> resolved env vars dict.
                     Produced by resolve_skill_env() per skill.
        """
        self._skill_env_map = env_map

    def set_global_env(self, global_env: dict[str, str]) -> None:
        """Set global env vars for injection during execution."""
        self._global_env = global_env

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

    async def execute(
        self,
        command: str,
        session_id: str | None = None,
        skill_paths: list[str] | None = None,
        timeout: int | None = None,
    ) -> dict[str, object]:
        """Execute a command (Bash or Python) through the injected CodeExecutor.

        Raises:
            BashExecutionError: on execution failure or missing session_id.
        """
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
                error_hint="Provide session_id in execute_command() call",
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

        if mcp_config_items and (timeout is None or timeout < _MCP_MIN_TIMEOUT):
            logger.warning("Auto-increased timeout %ss -> %ss for MCP skill execution", timeout, _MCP_MIN_TIMEOUT)
            timeout = _MCP_MIN_TIMEOUT

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

    async def spawn_background(
        self,
        command: str,
        session_id: str,
        *,
        finish_listener: "FinishListener | None" = None,
        progress_listener: "ProgressListener | None" = None,
    ) -> "BackgroundProcessInfo":
        """Spawn a long-running shell command and immediately return its PID.

        The command is launched under the same sandbox + workspace as
        ``execute()`` but wrapped as ``sh -c "<command>"`` so the LLM can keep
        using natural shell syntax (pipes, redirects, env vars). The returned
        handle is registered with the background process registry, allowing
        ``bash_process_*`` tools to inspect/kill the process later.

        Skill detection, python rewriting and MCP setup are intentionally
        bypassed: background jobs are by definition long-running shell tasks
        (dev servers, crawlers, watchers); the synchronous fast path is the
        right choice for skill/python workloads.

        No ``timeout`` argument: the background spawn primitive does not
        enforce an execution-time cap, and silently accepting one would
        mislead callers. To bound runtime, the caller schedules a follow-up
        ``bash_process_kill_tool(pid)``.
        """
        command = resolve_file_ids_in_text(command)
        from myrm_agent_harness.utils.text_utils import unwrap_markdown_fence

        unwrapped = unwrap_markdown_fence(command)
        if unwrapped is not command:
            command = unwrapped

        workspace, invalidated_workspace_id = await self._workspace_manager.get_or_create(session_id)
        if invalidated_workspace_id:
            self._skill_manager.clear_workspace_cache(invalidated_workspace_id)

        workspace_root_str = self._workspace_manager.get_workspace_path(workspace)
        if workspace_root_str:
            self._executor.bind_workspace(workspace_root_str)
        workspace_root = workspace_root_str or ""

        network_config = self.config.network

        from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext

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
                command=command,
                error_category="BACKGROUND_UNSUPPORTED",
                error_hint="Use a LocalExecutor backend or omit run_in_background.",
            )

        proc = await spawn_method(context)

        from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
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
            # Reap the just-spawned process so we do not orphan it under the OS.
            with suppress(ProcessLookupError, OSError):
                proc.kill()
            raise BashExecutionError(
                str(exc),
                phase="validation",
                command=command,
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

    def _prepare_execution(
        self,
        command: str,
        session_id: str | None = None,
        workspace_root: str | None = None,
    ) -> tuple[bool, str, list["MCPConfigItem"] | None]:
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
                # Mechanism-level transform: when the LLM still wraps Python in
                # ``python -c '...'`` (legacy habit), record an actionable hint
                # alongside the executor switch so ``bash_tool`` can surface it
                # back to the model. This is *not* a soft prompt — the code has
                # already been rerouted to file-mode execution, eliminating
                # shell-escape failures regardless of the LLM's compliance.
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
        """Pre-check extracted Python code via ``ast.parse`` before execution.

        Raises BashExecutionError with an actionable hint when the code is invalid,
        preventing a timeout-then-retry loop when broken code is sent to the executor.
        """
        from myrm_agent_harness.agent.skills.mcp.python_extractor import validate_python_syntax

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
        executor: "CodeExecutor",
        is_skill_execution: bool,
    ) -> "ExecutionResult":
        """Execute Python with full PTC (Programmatic Tool Calling) injection.

        When not in a nested PTC context and not a skill execution, starts a
        temporary PtcRpcServer exposing all Agent tools, generates myrm_tools.py
        stubs, and injects the socket path + PYTHONPATH into the subprocess env.
        The child process can then ``import myrm_tools`` to call any tool.
        """
        if is_skill_execution or _in_ptc_context.get() or not self._ptc_tools:
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
        import re

        match = re.search(r"from\s+skills\.([a-zA-Z0-9_]+)\s+import", code)
        if match:
            return match.group(1)

        match = re.search(r"import\s+skills\.([a-zA-Z0-9_]+)", code)
        if match:
            return match.group(1)

        match = re.search(r"\.claude/skills/([a-zA-Z0-9_]+)/", code)
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

    def _convert_to_container_paths(self, workspace_skill_paths: list[str], workspace: "Workspace") -> list[str]:
        """Convert local absolute paths to container paths (/workspace/...)."""
        workspace_root_str = self._workspace_manager.get_workspace_path(workspace)
        if not workspace_root_str:
            logger.warning(" workspace_root is empty, cannot convert paths")
            return []

        # Unified path conversion via WorkspacePathResolver
        return WorkspacePathResolver.to_container_paths(workspace_skill_paths, workspace_root_str)

    def _build_execution_context(
        self,
        prepared_code: str,
        original_code: str,
        mcp_config_items: list["MCPConfigItem"] | None,
        session_id: str | None,
        workspace: "Workspace | None",
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

        # Merge global env vars
        if self._global_env:
            if env is None:
                env = {}
            env.update(self._global_env)

        # Merge skill-declared env vars (apiKey mapping + per-skill config)
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
            timeout=timeout if timeout is not None else self._get_timeout(),
            env=env,
            allow_network=network_config.allow_network,
            allowed_hosts=network_config.get_effective_allowed_hosts(),
            mcp_config=mcp_config_items,
        )

    def _get_timeout(self) -> int:
        """Get execution timeout in seconds."""
        return self.config.local.max_execution_time

    def _register_generated_files(self, result: "ExecutionResult") -> None:
        """Register generated artifact files from execution result."""
        from myrm_agent_harness.agent.artifacts.registry import register_generated_files

        register_generated_files(generated_files=result.generated_files, container_id=result.container_id)

    def _build_error_details(self, result: "ExecutionResult") -> str:
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
