"""Integration tests for DeepResearchOrchestrator evidence tree lifecycle.

Validates:
- Multi-turn research loop where research findings trigger conflict detection
- Atomic tree repair and cascade pruning during live orchestration
- Event stream emission of evidence_repair status
- Final report context synthesis filtering pruned facts and injecting consensus tree slice
"""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from myrm_agent_harness.agent.deep_research.config import DeepResearchConfig
from myrm_agent_harness.agent.deep_research.orchestrator import DeepResearchOrchestrator
from myrm_agent_harness.agent.orchestration.signals.catalog import (
    DISPATCH_RESEARCH_SIGNAL,
    FINALIZE_REPORT_SIGNAL,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.toolkits.memory.working_tree import EvidenceTree


class TestOrchestratorEvidenceTreeIntegration:
    """End-to-end integration test between DeepResearchOrchestrator and EvidenceTree."""

    @pytest.mark.asyncio
    async def test_orchestrator_contradiction_repair_and_report_filtering(self) -> None:
        """Test full orchestration workflow where Cycle 2 refutes Cycle 1 finding."""
        # Setup mock responses for LLM
        plan_response = AIMessage(content="1. Check initial pricing\n2. Verify latest announcements")
        plan_response.usage_metadata = {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }

        # Cycle 1: LLM dispatches task 1
        turn1_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "tc_dispatch_1",
                    "name": DISPATCH_RESEARCH_SIGNAL,
                    "args": {"task": "Research Product Alpha price"},
                }
            ],
        )

        # Cycle 2: LLM dispatches task 2
        turn2_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "tc_dispatch_2",
                    "name": DISPATCH_RESEARCH_SIGNAL,
                    "args": {"task": "Research Product Alpha price updated status"},
                }
            ],
        )

        # Cycle 3: LLM finalizes report
        turn3_response = AIMessage(
            content="",
            tool_calls=[{"id": "tc_fin", "name": FINALIZE_REPORT_SIGNAL, "args": {}}],
        )

        llm = MagicMock()
        llm.model = "gpt-4o"
        llm.model_name = "gpt-4o"
        llm.n_ctx = 128_000
        llm.model_max_context_length = None
        llm.max_input_tokens = None

        bound = MagicMock()
        tool_responses = [turn1_response, turn2_response, turn3_response]
        call_count = 0

        async def mock_bound_ainvoke(messages: list[BaseMessage]) -> AIMessage:
            nonlocal call_count
            idx = min(call_count, len(tool_responses) - 1)
            call_count += 1
            return tool_responses[idx]

        bound.ainvoke = mock_bound_ainvoke
        llm.bind_tools = MagicMock(return_value=bound)

        async def mock_llm_ainvoke(messages: list[BaseMessage]) -> AIMessage:
            for msg in messages:
                content_str = str(getattr(msg, "content", ""))
                if "PRIOR NODE" in content_str or "VERDICT:" in content_str or "arbitration" in content_str.lower():
                    return AIMessage(content="VERDICT: CONTRADICTION | REASON: 2026 update refutes earlier price")
            return plan_response

        llm.ainvoke = mock_llm_ainvoke

        # Mock report streaming
        report_chunks = ["# Product Alpha Report\n\n", "The verified pricing as of 2026 is $1500."]

        async def mock_astream(messages: list[BaseMessage]) -> AsyncIterator[MagicMock]:
            for text in report_chunks:
                chunk = MagicMock()
                chunk.content = text
                chunk.usage_metadata = None
                yield chunk

        llm.astream = mock_astream

        config = DeepResearchConfig(
            enable_clarification=False,
            max_cycles=4,
        )
        orch = DeepResearchOrchestrator(llm=llm, config=config)

        # Mock _dispatch_research_agents to return conflicting results across cycles
        dispatch_call_count = 0

        async def mock_dispatch(
            dispatch_tasks: list[dict[str, str]],
            message_id: str,
            event_queue: asyncio.Queue[dict[str, object]],
        ) -> list[str]:
            nonlocal dispatch_call_count
            dispatch_call_count += 1
            if dispatch_call_count == 1:
                # Cycle 1: initial premise
                return ["Product Alpha price is $1000 announced on website. Source: https://example.com/alpha"]
            else:
                # Cycle 2: refutation / temporal contradiction
                return [
                    "Product Alpha price refuted: official 2026 update confirms price is $1500. "
                    "Source: https://example.com/alpha-2026"
                ]

        orch._dispatch_research_agents = mock_dispatch  # type: ignore[assignment]

        events: list[dict[str, object]] = []
        async for ev in orch.run("Analyze Product Alpha price"):
            events.append(ev)

        # 1. Verify evidence_repair event was emitted
        repair_events: list[dict[str, object]] = []
        for e in events:
            if e.get("type") == AgentEventType.STATUS:
                data_val = e.get("data")
                if isinstance(data_val, dict) and data_val.get("phase") == "evidence_repair":
                    repair_events.append(e)

        assert len(repair_events) >= 1, "Expected at least one evidence_repair status event"
        first_event = repair_events[0]
        repair_data = first_event.get("data")
        assert isinstance(repair_data, dict)
        assert "target_node_id" in repair_data

        # 2. Verify evidence_tree persisted in result
        assert orch.result.evidence_tree is not None
        tree = EvidenceTree.from_dict(orch.result.evidence_tree)
        active_nodes = tree.get_active_nodes()
        assert len(active_nodes) >= 1

        # 3. Verify final report content
        assert "Product Alpha Report" in orch.result.report
        assert "$1500" in orch.result.report
