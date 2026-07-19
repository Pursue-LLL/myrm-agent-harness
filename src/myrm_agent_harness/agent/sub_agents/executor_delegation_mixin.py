"""SubagentExecutor delegation tool attachment APIs.

[INPUT]
- .types::SubagentConfig, DelegateRole, DELEGATION_CAPABILITY_MANIFEST (POS: Subagent subsystem core type definitions.)
- agent.meta_tools.spawn_subagent (POS: Meta-tools for spawning and delegating to sub-agents.)

[OUTPUT]
- SubagentExecutorDelegationMixin._attach_child_delegation_tools

[POS]
Orchestrator-role child agents receive scoped delegation meta-tools (2 + teammate).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .types import DELEGATION_CAPABILITY_MANIFEST, DelegateRole, SubagentConfig

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent

logger = get_agent_logger(__name__)


class SubagentExecutorDelegationMixin:
    """Attach orchestrator delegation tools to child agents."""

    async def _attach_child_delegation_tools(
        self,
        *,
        child_agent: BaseAgent,
        agent_type: str,
        config: SubagentConfig,
    ) -> None:
        """Attach delegation tools that are scoped to the child agent's manager."""
        if config.delegation_role != DelegateRole.ORCHESTRATOR:
            return
        if config.delegation_catalog is None:
            logger.warning(
                "[subagent:%s] Orchestrator role requested but no delegation catalog is available",
                agent_type,
            )
            return

        from myrm_agent_harness.agent.meta_tools.spawn_subagent import (
            create_delegate_task_tool,
            create_send_teammate_message_tool,
            create_subagent_control_tool,
            update_delegate_task_description,
        )

        def child_tool_registry_getter() -> list[object]:
            return list(child_agent._cached_tools or child_agent.user_tools)

        allowed_types = sorted(config.delegation_allowed_types) if config.delegation_allowed_types is not None else None
        delegate_tool = create_delegate_task_tool(
            child_agent,
            tool_registry_getter=child_tool_registry_getter,
            catalog=config.delegation_catalog,
            parent_type=agent_type,
            allowed_types=allowed_types,
        )
        await update_delegate_task_description(delegate_tool, config.delegation_catalog, allowed_types)
        child_tool_by_name = {
            "delegate_task_tool": delegate_tool,
            "subagent_control_tool": create_subagent_control_tool(child_agent),
            "send_teammate_message_tool": create_send_teammate_message_tool(child_agent),
        }
        child_agent.add_tools(
            [child_tool_by_name[tool_name] for tool_name in DELEGATION_CAPABILITY_MANIFEST.orchestrator_child_tools]
        )
