"""Default AgentFactory for standalone ACP server usage.

Creates a BaseAgent for each ACP session. The LLM is the injected model, else one built from
the given LLMConfig, else one built from MYRM_* environment variables. With none of them
configured, session creation fails with the missing variable named; no stand-in model answers.
Override this module or provide SkillAgentFactory for full-featured skill and memory pipelines.

[INPUT]
- agent.base_agent::BaseAgent (POS: Base Agent — lightweight agent with streaming, token tracking, and artifacts.)
- core.config.llm::LLMConfig (POS: LLM configuration)
- toolkits.llms::LLMManager (POS: Cached LLMConfig to chat model construction) [lazy]

[OUTPUT]
- DefaultAgentFactory: Creates a BaseAgent with default configuration for each ACP session.

[POS]
Default AgentFactory for standalone ACP server usage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.core.config.llm import LLMConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.toolkits.mcp.config import MCPConfig

logger = logging.getLogger(__name__)


class DefaultAgentFactory:
    """Creates a BaseAgent with default configuration for each ACP session."""

    def __init__(
        self,
        llm: BaseChatModel | None = None,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self._llm = llm
        self._llm_config = llm_config

    async def create_agent(
        self,
        session_id: str,
        cwd: str,
        mcp_servers: list[MCPConfig] | None = None,
    ) -> BaseAgent:
        logger.info(
            "creating_default_agent session_id=%s cwd=%s mcp_count=%d",
            session_id,
            cwd,
            len(mcp_servers or []),
        )
        return BaseAgent(llm=await self._resolve_llm())

    async def _resolve_llm(self) -> BaseChatModel:
        if self._llm is not None:
            return self._llm

        from myrm_agent_harness.toolkits.llms import LLMManager

        config = self._llm_config or LLMConfig.from_env()
        return await LLMManager.get_llm_from_config(config, streaming=config.streaming)
