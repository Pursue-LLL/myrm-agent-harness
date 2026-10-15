"""Verifier selection shared by every entry that pairs a worker with a verifier.

[INPUT]
- agent.sub_agents.builder::filter_tools (POS: Subagent construction helpers. Prepare child agents without business-layer dependencies.)
- agent.sub_agents.spawn_prep::enforce_spawn_policy_on_config (POS: Single SSOT for spawn prep so delegate_task_tool and SpawnSubagentTool stay aligned.)
- agent.sub_agents.types::SubagentCatalog, SubagentConfig, WorkspacePolicy (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)

[OUTPUT]
- resolve_verifier: Pick the read-only verifier config for a worker and refuse a verifier that cannot run commands
- VerifierUnavailableError: Raised when the chosen verifier could never produce a verdict that counts

[POS]
A verifier's PASS only counts when the executor launched a process (the execution-evidence gate in
``_verifier_round``), and a verifier launches one through the bash tool. Refusing a verifier without that tool
before the worker spawns turns a verification that could only end BLOCKED into an actionable error.
"""

from __future__ import annotations

from dataclasses import replace

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.sub_agents.builder import filter_tools
from myrm_agent_harness.agent.sub_agents.spawn_prep import enforce_spawn_policy_on_config
from myrm_agent_harness.agent.sub_agents.types import SubagentCatalog, SubagentConfig, WorkspacePolicy
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

__all__ = ["VerifierUnavailableError", "resolve_verifier"]

_EXECUTION_TOOL = "bash_code_execute_tool"


class VerifierUnavailableError(ValueError):
    """The chosen verifier has no way to launch a process, so none of its PASS verdicts could count."""


async def resolve_verifier(
    catalog: SubagentCatalog | None,
    verifier_agent_type: str | None,
    worker_type: str,
    worker_base_config: SubagentConfig,
    parent_tools: list[BaseTool],
) -> tuple[str, SubagentConfig]:
    """Return the verifier type and its read-only config for ``worker_type``.

    The verifier defaults to the worker's type; an unknown type falls back to the worker's type and its
    ``worker_base_config``. That config must be the worker's as resolved, before spawn-time edits such as
    readonly mode, which strips the command tool and tells the agent not to run commands: a verifier
    inheriting that could never run the tests it is asked to run.

    Raises:
        VerifierUnavailableError: the verifier's tools, after the same filtering the spawn applies, lack
            the bash tool.
    """
    verifier_type = verifier_agent_type or worker_type
    config = await catalog.resolve(verifier_type) if catalog is not None else None
    if config is None:
        if verifier_type != worker_type:
            logger.warning(
                "Verifier agent type '%s' not found, falling back to worker type '%s'", verifier_type, worker_type
            )
        verifier_type, config = worker_type, enforce_spawn_policy_on_config(worker_base_config)

    config = replace(config, workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX)
    if not any(tool.name == _EXECUTION_TOOL for tool in filter_tools(config, parent_tools)):
        raise VerifierUnavailableError(
            f"Verifier agent type '{verifier_type}' cannot run commands ({_EXECUTION_TOOL} is not available to it), "
            "so no PASS from it can be confirmed. Set verifier_agent_type to an agent type that can run commands, "
            "or run without verification."
        )
    return verifier_type, config
