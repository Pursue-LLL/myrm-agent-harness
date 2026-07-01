"""Bash code execution orchestrator (aggregate root).

[INPUT]
- .bash_executor_execute_mixin::BashExecutorExecuteMixin (POS: Synchronous execute() orchestration.)
- .bash_executor_background_mixin::BashExecutorBackgroundMixin (POS: Background spawn via process registry.)
- .bash_executor_prepare_mixin::BashExecutorPrepareMixin (POS: MCP proxy, code-type detection, skill staging.)
- .bash_executor_context_mixin::BashExecutorContextMixin (POS: ExecutionContext build, logging, artifacts.)
- .bash_execution_error::BashExecutionError (POS: Structured execution error with diagnostics.)
- .bash_executor_constants::MCP_MIN_TIMEOUT (POS: MCP skill execution timeout floor.)

[OUTPUT]
- BashExecutor: Code execution orchestrator aggregate root
- BashExecutionError: Execution error with error_hint + error_category diagnostics
- _MCP_MIN_TIMEOUT: Backward-compatible alias for tests and bash_tool

[POS]
Bash executor aggregate root. MRO: Execute → Background → Prepare → Context (locked by architecture tests).
Public import path: ``from ...bash_executor import BashExecutor``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_execution import ExecutionConfig
from myrm_agent_harness.agent.meta_tools.bash.bash_execution_error import BashExecutionError
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_background_mixin import BashExecutorBackgroundMixin
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_constants import MCP_MIN_TIMEOUT
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_context_mixin import BashExecutorContextMixin
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_execute_mixin import BashExecutorExecuteMixin
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_prepare_mixin import BashExecutorPrepareMixin
from myrm_agent_harness.agent.meta_tools.bash.mcp_citation_handler import MCPMetadataExtractor
from myrm_agent_harness.agent.meta_tools.bash.skill_workspace_manager import SkillWorkspaceManager
from myrm_agent_harness.agent.meta_tools.bash.workspace_manager import WorkspaceManager

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

_MCP_MIN_TIMEOUT = MCP_MIN_TIMEOUT


class BashExecutor(
    BashExecutorExecuteMixin,
    BashExecutorBackgroundMixin,
    BashExecutorPrepareMixin,
    BashExecutorContextMixin,
):
    """Code execution orchestrator (DI-based, stateless per call)."""

    def __init__(
        self,
        executor: CodeExecutor,
        enable_skill_execution: bool = True,
        ptc_tools: list[BaseTool] | None = None,
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
        self._skill_oauth_issuers: dict[str, str] | None = None
        self._global_env: dict[str, str] | None = None

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
        """Set per-skill resolved env vars for injection during execution."""
        self._skill_env_map = env_map

    def set_skill_oauth_issuers(self, issuers: dict[str, str]) -> None:
        """Map skill directory name -> oauth issuer for scoped credential injection."""
        self._skill_oauth_issuers = issuers

    def set_global_env(self, global_env: dict[str, str]) -> None:
        """Set global env vars for injection during execution."""
        self._global_env = global_env


__all__ = ["BashExecutionError", "BashExecutor", "_MCP_MIN_TIMEOUT"]
