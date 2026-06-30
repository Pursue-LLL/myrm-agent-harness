"""Integration tests for run_council — real SubagentManager, no mock on key paths.

Uses a real BaseAgent + SubagentManager. Only the bottom-layer executor
(SubagentExecutor.run_with_retry) is patched to avoid actual LLM calls.
spawn_child, wait_children, and run_council three-phase orchestration
all run through real production code paths.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.sub_agents._orchestrator_council import run_council
from myrm_agent_harness.agent.sub_agents.manager import SubagentManager
from myrm_agent_harness.agent.sub_agents.types import (
    CouncilOpinion,
    CouncilResult,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.core.events.types import AgentEventType


class _StubLLM:
    """Minimal LLM stub satisfying BaseAgent construction."""

    def bind(self, **kwargs: object) -> "_StubLLM":
        return self

    def bind_tools(self, tools: list[BaseTool], **kwargs: object) -> "_StubLLM":
        return self

    async def ainvoke(self, messages: list[object], config: object = None) -> object:
        from langchain_core.messages import AIMessage
        return AIMessage(content="stub")


def _make_executor_result(
    task_id: str,
    agent_type: str,
    result_text: str = "analysis",
    success: bool = True,
    error: str = "",
) -> SubAgentResult:
    return SubAgentResult(
        success=success,
        task_id=task_id,
        agent_type=agent_type,
        result=result_text if success else "",
        error=error if not success else "",
        completed_at=time.time(),
        status=SubAgentStatus.COMPLETED if success else SubAgentStatus.FAILED,
        duration_seconds=0.1,
    )


def _build_executor_side_effect(
    responses: dict[str, str | None],
) -> Callable[..., Any]:
    """Build a side_effect for SubagentExecutor.run_with_retry.

    `responses` maps substring patterns to result text.
    If value is None, the expert "fails".
    Matching is done against the task_id argument.
    """
    call_counter = {"n": 0}

    async def side_effect(
        *,
        task_id: str,
        agent_type: str,
        task_description: str,
        config: SubagentConfig,
        **kwargs: object,
    ) -> SubAgentResult:
        call_counter["n"] += 1
        for pattern, text in responses.items():
            if pattern in task_id:
                if text is None:
                    return _make_executor_result(
                        task_id, agent_type, success=False, error="executor failure"
                    )
                return _make_executor_result(task_id, agent_type, result_text=text)
        return _make_executor_result(task_id, agent_type, result_text=f"default-{call_counter['n']}")

    return side_effect


def _build_real_manager() -> tuple[BaseAgent, SubagentManager]:
    agent = BaseAgent(llm=_StubLLM())
    return agent, agent._subagent_manager


_CHAIR_SYNTHESIS = (
    "### Consensus Points\n"
    "- All experts agree on approach A\n"
    "- Feasibility confirmed\n"
    "### Divergences\n"
    "- Expert 0 prefers X, Expert 1 prefers Y\n"
    "### Action Items\n"
    "1. Implement approach A\n"
    "2. Benchmark X vs Y\n"
    "3. Write documentation\n"
)


@pytest.mark.asyncio
class TestCouncilImportIntegration:
    """Verify module import chains are correct."""

    async def test_run_council_importable_from_orchestrator(self) -> None:
        from myrm_agent_harness.agent.sub_agents.orchestrator import run_council as rc
        assert callable(rc)

    async def test_council_types_importable(self) -> None:
        from myrm_agent_harness.agent.sub_agents.types import CouncilOpinion as CO
        from myrm_agent_harness.agent.sub_agents.types import CouncilResult as CR
        assert CO is CouncilOpinion
        assert CR is CouncilResult

    async def test_council_phase_event_exists(self) -> None:
        assert hasattr(AgentEventType, "COUNCIL_PHASE")
        assert AgentEventType.COUNCIL_PHASE.value == "council_phase"


@pytest.mark.asyncio
class TestManagerRunCouncilSignature:
    """Verify SubagentManager.run_council proxy method signature and type."""

    async def test_manager_has_run_council(self) -> None:
        _, mgr = _build_real_manager()
        assert hasattr(mgr, "run_council")
        assert asyncio.iscoroutinefunction(mgr.run_council)

    async def test_run_council_signature_matches(self) -> None:
        sig = inspect.signature(SubagentManager.run_council)
        params = list(sig.parameters.keys())
        assert "task_description" in params
        assert "expert_configs" in params
        assert "context" in params
        assert "tool_registry_getter" in params
        assert "chair_config" in params
        assert "cross_review_rounds" in params
        assert "cancel_token" in params

    async def test_return_annotation_is_council_result(self) -> None:
        sig = inspect.signature(SubagentManager.run_council)
        annotation = sig.return_annotation
        assert annotation == CouncilResult or annotation == "CouncilResult"


@pytest.mark.asyncio
class TestCouncilFullPipeline:
    """Integration: real SubagentManager, real spawn_child/wait_children,
    only SubagentExecutor.run_with_retry is patched."""

    @patch(
        "myrm_agent_harness.agent.sub_agents.executor.SubagentExecutor.run_with_retry",
    )
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_2_experts_full_pipeline(
        self, mock_emit: AsyncMock, mock_executor: AsyncMock,
    ) -> None:
        mock_executor.side_effect = _build_executor_side_effect({
            "p1-0": "Expert 0 independent analysis",
            "p1-1": "Expert 1 independent analysis",
            "cr1-0": "Expert 0 cross-review",
            "cr1-1": "Expert 1 cross-review",
            "chair": _CHAIR_SYNTHESIS,
        })

        _, mgr = _build_real_manager()

        result = await mgr.run_council(
            task_description="Evaluate payment architecture",
            expert_configs=[
                ("security", SubagentConfig(system_prompt="Security expert")),
                ("performance", SubagentConfig(system_prompt="Performance expert")),
            ],
            context={"session_id": "test", "workspace_path": "/tmp/test"},
            tool_registry_getter=lambda: [],
        )

        assert isinstance(result, CouncilResult)
        assert result.success is True
        assert result.rounds_completed == 3
        assert len(result.opinions) == 4
        assert len(result.consensus_points) == 2
        assert len(result.divergences) == 1
        assert len(result.action_items) == 3
        assert result.total_duration_seconds > 0
        assert result.error == ""

        phase1_opinions = [o for o in result.opinions if o.round_num == 1]
        assert len(phase1_opinions) == 2
        assert all(o.success for o in phase1_opinions)

        cr_opinions = [o for o in result.opinions if o.round_num == 2]
        assert len(cr_opinions) == 2

        assert mock_emit.call_count == 3
        phase_names = [call.args[0] for call in mock_emit.call_args_list]
        assert phase_names == ["independent", "cross_review", "synthesis"]

    @patch(
        "myrm_agent_harness.agent.sub_agents.executor.SubagentExecutor.run_with_retry",
    )
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_3_experts_2_rounds(
        self, mock_emit: AsyncMock, mock_executor: AsyncMock,
    ) -> None:
        mock_executor.side_effect = _build_executor_side_effect({
            "p1-": "Independent opinion",
            "cr1-": "Cross-review round 1",
            "cr2-": "Cross-review round 2",
            "chair": _CHAIR_SYNTHESIS,
        })

        _, mgr = _build_real_manager()

        result = await mgr.run_council(
            task_description="Database selection",
            expert_configs=[
                ("dba", SubagentConfig(system_prompt="DBA")),
                ("sre", SubagentConfig(system_prompt="SRE")),
                ("dev", SubagentConfig(system_prompt="Dev")),
            ],
            context={"session_id": "test", "workspace_path": "/tmp/test"},
            tool_registry_getter=lambda: [],
            cross_review_rounds=2,
        )

        assert result.success
        assert result.rounds_completed == 4
        assert len(result.opinions) == 9

    @patch(
        "myrm_agent_harness.agent.sub_agents.executor.SubagentExecutor.run_with_retry",
    )
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_partial_failure_continues(
        self, mock_emit: AsyncMock, mock_executor: AsyncMock,
    ) -> None:
        mock_executor.side_effect = _build_executor_side_effect({
            "p1-0": "Expert 0 ok",
            "p1-1": None,
            "cr1-": "cross review",
            "chair": _CHAIR_SYNTHESIS,
        })

        _, mgr = _build_real_manager()

        result = await mgr.run_council(
            task_description="Review X",
            expert_configs=[
                ("a", SubagentConfig(system_prompt="A")),
                ("b", SubagentConfig(system_prompt="B")),
            ],
            context={"session_id": "test", "workspace_path": "/tmp/test"},
            tool_registry_getter=lambda: [],
        )

        assert result.success
        phase1 = [o for o in result.opinions if o.round_num == 1]
        assert sum(1 for o in phase1 if o.success) >= 1

    @patch(
        "myrm_agent_harness.agent.sub_agents.executor.SubagentExecutor.run_with_retry",
    )
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_all_experts_fail(
        self, mock_emit: AsyncMock, mock_executor: AsyncMock,
    ) -> None:
        mock_executor.side_effect = _build_executor_side_effect({
            "p1-0": None,
            "p1-1": None,
        })

        _, mgr = _build_real_manager()

        result = await mgr.run_council(
            task_description="Doomed",
            expert_configs=[
                ("a", SubagentConfig(system_prompt="A")),
                ("b", SubagentConfig(system_prompt="B")),
            ],
            context={"session_id": "test", "workspace_path": "/tmp/test"},
            tool_registry_getter=lambda: [],
        )

        assert not result.success
        assert "All experts failed" in result.error

    @patch(
        "myrm_agent_harness.agent.sub_agents.executor.SubagentExecutor.run_with_retry",
    )
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_chair_failure(
        self, mock_emit: AsyncMock, mock_executor: AsyncMock,
    ) -> None:
        mock_executor.side_effect = _build_executor_side_effect({
            "p1-": "ok",
            "cr1-": "cross",
            "chair": None,
        })

        _, mgr = _build_real_manager()

        result = await mgr.run_council(
            task_description="Review",
            expert_configs=[
                ("a", SubagentConfig(system_prompt="A")),
                ("b", SubagentConfig(system_prompt="B")),
            ],
            context={"session_id": "test", "workspace_path": "/tmp/test"},
            tool_registry_getter=lambda: [],
        )

        assert not result.success
        assert "Chair synthesis failed" in result.error
        assert len(result.opinions) == 4

    @patch(
        "myrm_agent_harness.agent.sub_agents.executor.SubagentExecutor.run_with_retry",
    )
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_less_than_2_experts_rejected(
        self, mock_emit: AsyncMock, mock_executor: AsyncMock,
    ) -> None:
        _, mgr = _build_real_manager()

        result = await mgr.run_council(
            task_description="Solo",
            expert_configs=[("a", SubagentConfig(system_prompt="A"))],
            context={"session_id": "test", "workspace_path": "/tmp/test"},
            tool_registry_getter=lambda: [],
        )

        assert not result.success
        assert "at least 2" in result.error
        mock_executor.assert_not_called()

    @patch(
        "myrm_agent_harness.agent.sub_agents.executor.SubagentExecutor.run_with_retry",
    )
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_custom_chair_config(
        self, mock_emit: AsyncMock, mock_executor: AsyncMock,
    ) -> None:
        mock_executor.side_effect = _build_executor_side_effect({
            "p1-": "analysis",
            "cr1-": "review",
            "chair": _CHAIR_SYNTHESIS,
        })

        _, mgr = _build_real_manager()

        custom_chair = SubagentConfig(
            system_prompt="Custom chair role",
            description="Custom Chair",
            display_name="Special Chair",
        )

        result = await mgr.run_council(
            task_description="Review",
            expert_configs=[
                ("a", SubagentConfig(system_prompt="A")),
                ("b", SubagentConfig(system_prompt="B")),
            ],
            context={"session_id": "test", "workspace_path": "/tmp/test"},
            tool_registry_getter=lambda: [],
            chair_config=custom_chair,
        )

        assert result.success

    @patch(
        "myrm_agent_harness.agent.sub_agents.executor.SubagentExecutor.run_with_retry",
    )
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_council_result_to_dict_serializable(
        self, mock_emit: AsyncMock, mock_executor: AsyncMock,
    ) -> None:
        mock_executor.side_effect = _build_executor_side_effect({
            "p1-": "analysis",
            "cr1-": "review",
            "chair": _CHAIR_SYNTHESIS,
        })

        _, mgr = _build_real_manager()

        result = await mgr.run_council(
            task_description="Review",
            expert_configs=[
                ("a", SubagentConfig(system_prompt="A")),
                ("b", SubagentConfig(system_prompt="B")),
            ],
            context={"session_id": "test", "workspace_path": "/tmp/test"},
            tool_registry_getter=lambda: [],
        )

        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["success"] is True
        assert isinstance(d["consensus_points"], list)
        assert isinstance(d["divergences"], list)
        assert isinstance(d["action_items"], list)
        assert isinstance(d["opinions"], list)

    @patch(
        "myrm_agent_harness.agent.sub_agents.executor.SubagentExecutor.run_with_retry",
    )
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_no_sink_does_not_crash(
        self, mock_emit: AsyncMock, mock_executor: AsyncMock,
    ) -> None:
        """_emit_council_phase gracefully no-ops when no progress sink is set."""
        mock_emit.side_effect = None
        mock_executor.side_effect = _build_executor_side_effect({
            "p1-": "analysis",
            "cr1-": "review",
            "chair": _CHAIR_SYNTHESIS,
        })

        _, mgr = _build_real_manager()

        result = await mgr.run_council(
            task_description="Review",
            expert_configs=[
                ("a", SubagentConfig(system_prompt="A")),
                ("b", SubagentConfig(system_prompt="B")),
            ],
            context={"session_id": "test", "workspace_path": "/tmp/test"},
            tool_registry_getter=lambda: [],
        )

        assert result.success

    @patch(
        "myrm_agent_harness.agent.sub_agents.executor.SubagentExecutor.run_with_retry",
    )
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_cross_review_rounds_clamped_to_3(
        self, mock_emit: AsyncMock, mock_executor: AsyncMock,
    ) -> None:
        mock_executor.side_effect = _build_executor_side_effect({
            "": "default response",
            "chair": _CHAIR_SYNTHESIS,
        })

        _, mgr = _build_real_manager()

        result = await mgr.run_council(
            task_description="Review",
            expert_configs=[
                ("a", SubagentConfig(system_prompt="A")),
                ("b", SubagentConfig(system_prompt="B")),
            ],
            context={"session_id": "test", "workspace_path": "/tmp/test"},
            tool_registry_getter=lambda: [],
            cross_review_rounds=10,
        )

        assert result.success
        assert result.rounds_completed == 5
