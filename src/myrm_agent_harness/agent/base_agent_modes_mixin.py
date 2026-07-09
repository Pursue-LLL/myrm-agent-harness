"""BaseAgent deep research and consensus entrypoints.

[POS]
Mixin: run_deep_research and run_consensus on BaseAgent.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.utils.chat_utils import ChatHistoryReq

from .streaming.message_builder import build_messages

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.agent.deep_research import DeepResearchConfig
    from myrm_agent_harness.agent.deep_research.orchestrator import (
        ClarifyCallback,
        CycleCallback,
        PlanCallback,
    )
    from myrm_agent_harness.toolkits.llms.consensus.types import ConsensusConfig, ConsensusResult
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken


class BaseAgentModesMixin:
    async def run_deep_research(
        self,
        query: str,
        chat_history: ChatHistoryReq | list[BaseMessage] | None = None,
        message_id: str | None = None,
        context: dict[str, Any] | None = None,
        cancel_token: CancellationToken | None = None,
        config: DeepResearchConfig | None = None,
        on_clarify: ClarifyCallback | None = None,
        on_plan_ready: PlanCallback | None = None,
        on_cycle_complete: CycleCallback | None = None,
    ) -> AsyncGenerator[dict[str, object]]:
        """Run Deep Research mode — multi-phase orchestrated research."""
        from myrm_agent_harness.agent.deep_research import (
            DeepResearchConfig,
            DeepResearchOrchestrator,
        )

        await self._ensure_initialized()
        message_id = message_id or str(uuid4())

        merged_context = await self._setup_workspace(context, message_id)

        from langchain_core.messages import BaseMessage as LCBaseMessage

        lc_history: list[LCBaseMessage] | None = None
        if chat_history:
            lc_history = build_messages("", chat_history)[:-1] if chat_history else None

        orchestrator = DeepResearchOrchestrator(
            llm=self.llm,
            config=config or DeepResearchConfig(),
            parent_tools=self._cached_tools if self._cached_tools else self.user_tools,
            cancel_token=cancel_token,
            context=merged_context,
            executor=self.executor,
            on_clarify=on_clarify,
            on_plan_ready=on_plan_ready,
            on_cycle_complete=on_cycle_complete,
        )

        async for event in orchestrator.run(
            query=query,
            chat_history=lc_history,
            message_id=message_id,
            context=merged_context,
        ):
            yield event

    async def run_consensus(
        self,
        query: str,
        reference_llms: list[BaseChatModel] | None = None,
        aggregator_llm: BaseChatModel | None = None,
        config: ConsensusConfig | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ConsensusResult:
        """Run Mixture-of-Agents consensus inference."""
        from myrm_agent_harness.toolkits.llms.consensus import (
            ConsensusConfig,
            ConsensusEngine,
        )

        refs = reference_llms or [self.llm]
        agg = aggregator_llm or self.llm
        engine = ConsensusEngine(
            reference_llms=refs,
            aggregator_llm=agg,
            config=config or ConsensusConfig(),
        )
        return await engine.run(query, system_prompt=self.system_prompt, cancel_token=cancel_token)
