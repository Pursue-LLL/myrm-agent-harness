"""SkillAgent Factory for standalone ACP server and enterprise IDE integration.

Creates a full-featured SkillAgent for each ACP session, binding workspace,
LLM configuration, skills, memory, and host-supplied dynamic MCP servers.

[INPUT]
- agent.types::AgentRuntimeSpec, WorkspaceBinding (POS: Agent runtime types)
- agent._factory.builder::create_skill_agent (POS: SkillAgent factory assembly)
- core.config.llm::LLMConfig (POS: LLM configuration)
- toolkits.mcp.config::MCPConfig (POS: MCP server configuration)

[OUTPUT]
- SkillAgentFactory: Creates a full-featured SkillAgent per ACP session

[POS]
Factory layer assembling enterprise-grade SkillAgent instances for ACP protocol sessions.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.types import AgentRuntimeSpec, WorkspaceBinding

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.skill_agent.skill_agent import SkillAgent
    from myrm_agent_harness.core.config.llm import LLMConfig
    from myrm_agent_harness.toolkits.mcp.config import MCPConfig

logger = logging.getLogger(__name__)


class SkillAgentFactory:
    """Creates a full-featured SkillAgent for each ACP session.

    Dynamically attaches session workspace, host MCP servers, and configured skills.
    """

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        llm: BaseChatModel | None = None,
        system_prompt: str | None = None,
        allowed_tools: Sequence[str] | None = None,
        skill_ids: Sequence[str] | None = None,
        extra_tools: Sequence[BaseTool] | None = None,
    ) -> None:
        self._llm_config = llm_config
        self._llm = llm
        self._system_prompt = system_prompt
        self._allowed_tools = list(allowed_tools) if allowed_tools else []
        self._skill_ids = list(skill_ids) if skill_ids else []
        self._extra_tools = list(extra_tools) if extra_tools else []

    async def create_agent(
        self,
        session_id: str,
        cwd: str,
        mcp_servers: list[MCPConfig] | None = None,
    ) -> SkillAgent:
        """Create and configure a SkillAgent instance for this session."""
        from myrm_agent_harness.agent._factory.builder import create_skill_agent

        workspace = WorkspaceBinding(
            mode="chat",
            root_path=cwd,
            chat_id=session_id,
        )

        all_mcp = list(mcp_servers or [])

        spec = AgentRuntimeSpec(
            agent_id=f"acp_{session_id[:8]}",
            name="Myrm ACP Agent",
            system_prompt=self._system_prompt,
            allowed_tools=self._allowed_tools,
            skill_ids=self._skill_ids,
            mcp_servers=all_mcp,
            workspace_binding=workspace,
        )

        llm_config = self._llm_config
        if llm_config is None and self._llm is None:
            try:
                from myrm_agent_harness.core.config.llm import LLMConfig

                llm_config = LLMConfig.from_env()
            except Exception as exc:
                logger.debug("acp_llm_config_env_not_found error=%s", exc)

        logger.info(
            "creating_skill_agent session_id=%s cwd=%s mcp_count=%d",
            session_id,
            cwd,
            len(all_mcp),
        )

        return await create_skill_agent(
            spec=spec,
            llm_config=llm_config,
            llm=self._llm,
            tools=self._extra_tools or None,
        )
