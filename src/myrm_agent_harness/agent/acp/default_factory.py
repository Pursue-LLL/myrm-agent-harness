"""Default AgentFactory for standalone ACP server usage.

Creates a BaseAgent for each ACP session. Resolves LLM from environment
or custom initialization parameters. Override this module or provide
SkillAgentFactory for full-featured skill and memory pipelines.

[INPUT]
- agent.base_agent::BaseAgent (POS: Base Agent — lightweight agent with streaming, token tracking, and artifacts.)
- core.config.llm::LLMConfig (POS: LLM configuration)

[OUTPUT]
- DefaultAgentFactory: Creates a BaseAgent with default configuration for each ACP session.

[POS]
Default AgentFactory for standalone ACP server usage.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.base_agent import BaseAgent

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.core.config.llm import LLMConfig
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

        llm = self._llm
        if llm is None:
            config = self._llm_config
            if config is None:
                try:
                    from myrm_agent_harness.core.config.llm import LLMConfig

                    config = LLMConfig.from_env()
                except Exception:
                    pass

            if config is not None:
                from myrm_agent_harness.core.llm.factory import create_chat_model

                llm = create_chat_model(config)

        if llm is None:
            # Fallback to FakeListChatModel for mock/offline scenarios where no env is provided
            from langchain_core.language_models import FakeListChatModel

            llm = FakeListChatModel(responses=["OK"])

        return BaseAgent(llm=llm)
