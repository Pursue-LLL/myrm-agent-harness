"""Default AgentFactory for standalone ACP server usage.

Creates a minimal BaseAgent for each ACP session. Override this module
or provide a custom AgentFactory to use SkillAgent or business-specific
agent configurations.

[INPUT]
- agent.base_agent::BaseAgent (POS: Base Agent — lightweight agent with streaming, token tracking, and artifacts.)

[OUTPUT]
- DefaultAgentFactory: Creates a BaseAgent with default configuration for each ACP session.

[POS]
Default AgentFactory for standalone ACP server usage.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.agent.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class DefaultAgentFactory:
    """Creates a BaseAgent with default configuration for each ACP session."""

    async def create_agent(
        self,
        session_id: str,
        cwd: str,
    ) -> BaseAgent:
        logger.info("creating_default_agent session_id=%s cwd=%s", session_id, cwd)
        return BaseAgent()
