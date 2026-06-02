"""
Myrm Agent Harness SDK Facade.

[INPUT]
- agent.skill_agent_factory::create_skill_agent (POS: Agent factory function)
- agent.skill_agent::SkillAgent (POS: Skill Agent implementation)
- agent.types::AgentRuntimeSpec, EngineParams, WorkspaceBinding (POS: Agent core runtime type definitions)
- agent.config::LLMConfig (POS: LLM configuration)

[OUTPUT]
- AgentClient: SDK facade providing clean, fluent API to configure and run the Agent framework.

[POS] SDK入口层。对外暴露 AgentClient，隐藏 AgentRuntimeSpec 和 EventStream 解析复杂度。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.agent.config import LLMConfig
from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.skill_agent_factory import create_skill_agent
from myrm_agent_harness.agent.types import AgentRuntimeSpec, EngineParams, WorkspaceBinding

logger = logging.getLogger(__name__)


class AgentClient:
    """SDK Output Layer for running myrm-agent-harness smoothly."""

    def __init__(
        self,
        llm: str | BaseChatModel | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        agent_id: str | None = None,
        name: str = "MyrmAgent",
        system_prompt: str | None = None,
    ):
        """Initialize the client.

        Args:
            llm: Model string (e.g., 'gpt-4o') or BaseChatModel instance.
            api_key: API key if passing a model string.
            base_url: Base URL if passing a model string.
            agent_id: Optional ID for the agent instance.
            name: Display name.
            system_prompt: Core instruction for the agent.
        """
        self.llm_config = None
        self.llm_instance = None
        self.agent_id = agent_id
        self.name = name
        self.system_prompt = system_prompt

        self.allowed_tools: list[str] = []
        self.skill_ids: list[str] = []
        self.skill_configs: dict[str, dict] = {}
        self.engine_params = EngineParams()
        self._workspace: WorkspaceBinding | None = None

        if isinstance(llm, str):
            import os
            self.llm_config = LLMConfig(
                model=llm,
                api_key=api_key or os.environ.get("OPENAI_API_KEY", "dummy_key"),
                base_url=base_url,
                streaming=True,
            )
        else:
            self.llm_instance = llm

    def with_tools(self, tools: list[str]) -> AgentClient:
        """Enable built-in tools (e.g., 'web_search', 'computer_use')."""
        self.allowed_tools.extend(tools)
        return self

    def with_skills(self, skill_ids: list[str], configs: dict[str, dict] | None = None) -> AgentClient:
        """Enable custom skills."""
        self.skill_ids.extend(skill_ids)
        if configs:
            self.skill_configs.update(configs)
        return self

    def with_workspace(self, root_path: str, mode: str = "cli") -> AgentClient:
        """Configure local execution workspace."""
        self._workspace = WorkspaceBinding(mode=mode, root_path=root_path)
        return self

    async def _build_agent(self) -> SkillAgent:
        """Construct the underlying SkillAgent instance."""
        import dataclasses
        spec = AgentRuntimeSpec(
            agent_id=self.agent_id,
            name=self.name,
            system_prompt=self.system_prompt,
            allowed_tools=self.allowed_tools,
            skill_ids=self.skill_ids,
            skill_configs=self.skill_configs or None,
            engine_params=dataclasses.asdict(self.engine_params),
            workspace_binding=self._workspace,
        )

        return await create_skill_agent(
            spec=spec,
            llm_config=self.llm_config,
            llm=self.llm_instance,
        )

    async def run_stream(
        self,
        prompt: str,
        on_thought: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, str], None] | None = None,
        on_message: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_approval: Callable[[dict], None] | None = None,
    ) -> str:
        """Run the agent and stream events to callbacks.

        Returns:
            The final aggregated assistant message.
        """
        agent = await self._build_agent()
        final_message = []

        try:
            async for event in agent.run(prompt):
                if not isinstance(event, dict):
                    continue

                event_type = event.get("type", "")

                if event_type == "reasoning" and on_thought:
                    on_thought(str(event.get("data", "")))
                elif event_type == "tasks_steps" and on_tool_call:
                    tool_name = str(event.get("tool_name", "") or event.get("step_key", ""))
                    on_tool_call(tool_name, str(event.get("data", "")))
                elif event_type == "message":
                    chunk = str(event.get("data", ""))
                    final_message.append(chunk)
                    if on_message:
                        on_message(chunk)
                elif event_type == "error" and on_error:
                    on_error(str(event.get("error", "Unknown error")))
                elif event_type == "tool_approval_request" and on_approval:
                    on_approval(event.get("data", {}))
        finally:
            if hasattr(agent, "close"):
                await agent.close()

        return "".join(final_message)

    async def run_and_wait(self, prompt: str) -> str:
        """Run the agent and wait for the final message.

        Returns:
            The final aggregated assistant message.
        """
        return await self.run_stream(prompt)
