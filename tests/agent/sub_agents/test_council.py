"""Tests for sub_agents/_orchestrator_council.py — run_council orchestration."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents._orchestrator_council import (
    _format_all_opinions,
    _format_opinions_for_injection,
    _parse_chair_sections,
    run_council,
)
from myrm_agent_harness.agent.sub_agents.types import (
    CouncilOpinion,
    CouncilResult,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)


def _ok(task_id: str = "t1", agent_type: str = "expert", result: str = "analysis") -> SubAgentResult:
    return SubAgentResult(
        success=True,
        task_id=task_id,
        agent_type=agent_type,
        result=result,
        completed_at=time.time(),
        status=SubAgentStatus.COMPLETED,
        duration_seconds=1.0,
    )


def _fail(task_id: str = "t1", agent_type: str = "expert", error: str = "failed") -> SubAgentResult:
    return SubAgentResult(
        success=False,
        task_id=task_id,
        agent_type=agent_type,
        error=error,
        completed_at=time.time(),
        status=SubAgentStatus.FAILED,
    )


def _make_config(prompt: str = "You are an expert.") -> SubagentConfig:
    return SubagentConfig(system_prompt=prompt)


def _make_manager(spawn_results: list[SubAgentResult]) -> MagicMock:
    """Create a mock SubagentManager that returns results in order.

    Non-waited spawns immediately populate child_results so wait_children
    can find them without hanging on asyncio.wait.
    """
    mgr = MagicMock()
    call_idx = 0
    child_results: dict[str, SubAgentResult] = {}

    mgr.children = {}

    async def mock_spawn_child(
        task_id: str,
        agent_type: str,
        task_description: str,
        config: SubagentConfig,
        context: dict,
        tool_registry_getter: object,
        wait: bool = True,
        cancel_token: object = None,
        **kwargs: object,
    ) -> SubAgentResult:
        nonlocal call_idx
        idx = min(call_idx, len(spawn_results) - 1)
        template = spawn_results[idx]
        actual_result = SubAgentResult(
            success=template.success,
            task_id=task_id,
            agent_type=agent_type,
            result=template.result,
            error=template.error,
            completed_at=time.time(),
            status=template.status,
            duration_seconds=template.duration_seconds,
        )
        child_results[task_id] = actual_result
        call_idx += 1
        return actual_result

    mgr.spawn_child = AsyncMock(side_effect=mock_spawn_child)
    mgr.child_results = child_results
    return mgr


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestFormatOpinionsForInjection:
    def test_excludes_self(self) -> None:
        opinions = [
            CouncilOpinion("expert-0-a", "a", 1, "Opinion A", True),
            CouncilOpinion("expert-1-b", "b", 1, "Opinion B", True),
            CouncilOpinion("expert-2-c", "c", 1, "Opinion C", True),
        ]
        result = _format_opinions_for_injection(opinions, "expert-1-b")
        assert "expert-0-a" in result
        assert "expert-2-c" in result
        assert "expert-1-b" not in result

    def test_empty_when_no_others(self) -> None:
        opinions = [CouncilOpinion("expert-0-a", "a", 1, "Only me", True)]
        result = _format_opinions_for_injection(opinions, "expert-0-a")
        assert "No other opinions" in result

    def test_formats_content(self) -> None:
        opinions = [
            CouncilOpinion("expert-0-a", "a", 1, "Analysis text here", True),
        ]
        result = _format_opinions_for_injection(opinions, "expert-99-z")
        assert "Analysis text here" in result
        assert "expert-0-a" in result


class TestFormatAllOpinions:
    def test_groups_by_round(self) -> None:
        opinions = [
            CouncilOpinion("e0", "a", 1, "Round 1 opinion", True),
            CouncilOpinion("e1", "b", 1, "Round 1 opinion B", True),
            CouncilOpinion("e0", "a", 2, "Round 2 opinion", True),
        ]
        result = _format_all_opinions(opinions)
        assert "Round 1" in result
        assert "Round 2" in result
        assert "Independent Analysis" in result
        assert "Cross-Review" in result

    def test_empty_list(self) -> None:
        result = _format_all_opinions([])
        assert result == ""


class TestParseChairSections:
    def test_parses_all_sections(self) -> None:
        text = """
### Consensus Points
- Everyone agrees on X
- Y is also agreed upon

### Divergences
- Expert A says Z, Expert B says W

### Action Items
- Implement X first
- Review Y second
"""
        consensus, divergences, actions = _parse_chair_sections(text)
        assert len(consensus) == 2
        assert "Everyone agrees on X" in consensus[0]
        assert len(divergences) == 1
        assert len(actions) == 2

    def test_handles_numbered_lists(self) -> None:
        text = """
### 1. Consensus Points
1. First consensus
2. Second consensus

### 2. Divergences
1. A disagreement

### 3. Action Items
1. Do this
"""
        consensus, divergences, actions = _parse_chair_sections(text)
        assert len(consensus) == 2
        assert len(divergences) == 1
        assert len(actions) == 1

    def test_handles_double_digit_numbered_items(self) -> None:
        text = """
### Action Items
1. First
2. Second
3. Third
4. Fourth
5. Fifth
6. Sixth
7. Seventh
8. Eighth
9. Ninth
10. Tenth item
11. Eleventh item
"""
        _, _, actions = _parse_chair_sections(text)
        assert len(actions) == 11
        assert "Tenth item" in actions[9]
        assert "Eleventh item" in actions[10]

    def test_handles_missing_sections(self) -> None:
        text = "Just some random analysis without proper headings."
        consensus, divergences, actions = _parse_chair_sections(text)
        assert consensus == ()
        assert divergences == ()
        assert actions == ()


# ---------------------------------------------------------------------------
# CouncilResult / CouncilOpinion dataclass tests
# ---------------------------------------------------------------------------


class TestCouncilTypes:
    def test_council_opinion_frozen(self) -> None:
        op = CouncilOpinion("e1", "expert", 1, "analysis", True, 2.5)
        assert op.expert_id == "e1"
        assert op.duration_seconds == 2.5

    def test_council_result_to_dict(self) -> None:
        result = CouncilResult(
            success=True,
            synthesis="Final synthesis",
            consensus_points=("Point 1",),
            divergences=("Div 1",),
            action_items=("Action 1",),
            opinions=(CouncilOpinion("e1", "a", 1, "text", True),),
            rounds_completed=3,
            total_duration_seconds=15.123,
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["synthesis"] == "Final synthesis"
        assert d["consensus_points"] == ["Point 1"]
        assert len(d["opinions"]) == 1
        assert "error" not in d

    def test_council_result_to_dict_with_error(self) -> None:
        result = CouncilResult(success=False, synthesis="", error="Something broke")
        d = result.to_dict()
        assert d["error"] == "Something broke"

    def test_opinion_content_truncated_in_dict(self) -> None:
        long_content = "x" * 1000
        result = CouncilResult(
            success=True,
            synthesis="ok",
            opinions=(CouncilOpinion("e1", "a", 1, long_content, True),),
        )
        d = result.to_dict()
        assert len(d["opinions"][0]["content"]) == 500


# ---------------------------------------------------------------------------
# run_council integration tests (with mocked wait_children)
# ---------------------------------------------------------------------------


async def _mock_wait_children_fn(
    mgr: object,
    task_ids: list[str],
    min_success_rate: float = 0.5,
    timeout: float | None = None,
) -> dict[str, object]:
    results_map = getattr(mgr, "child_results", {})
    successes: list[dict[str, object]] = []
    failures: list[object] = []
    for tid in task_ids:
        completed = results_map.get(tid)
        if completed is not None:
            data = completed.to_dict()
            (successes if completed.success else failures).append(data)
        else:
            failures.append({"task_id": tid, "error": "not found"})
    rate = len(successes) / len(task_ids) if task_ids else 0.0
    return {
        "success": rate >= min_success_rate,
        "results": successes,
        "success_rate": rate,
        "failures": failures,
    }


@pytest.fixture()
def _mock_wait_children():
    """Patch _get_wait_children to return a mock that reads child_results directly."""
    with patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._get_wait_children",
        return_value=_mock_wait_children_fn,
    ):
        yield


@pytest.mark.usefixtures("_mock_wait_children")
class TestRunCouncil:
    @pytest.mark.asyncio
    async def test_requires_at_least_2_experts(self) -> None:
        mgr = _make_manager([_ok()])
        result = await run_council(
            manager=mgr,
            task_description="Review X",
            expert_configs=[("expert", _make_config())],
            context={},
            tool_registry_getter=lambda: [],
        )
        assert not result.success
        assert "at least 2 experts" in result.error

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_basic_2_experts_1_round(self, mock_emit: AsyncMock) -> None:
        chair_text = (
            "### Consensus Points\n- Both agree on A\n\n"
            "### Divergences\n- None\n\n"
            "### Action Items\n- Implement A\n"
        )
        spawn_results = [
            _ok(result="Expert 0 analysis"),
            _ok(result="Expert 1 analysis"),
            _ok(result="Expert 0 cross-review"),
            _ok(result="Expert 1 cross-review"),
            _ok(result=chair_text),
        ]
        mgr = _make_manager(spawn_results)

        result = await run_council(
            manager=mgr,
            task_description="Review payment system design",
            expert_configs=[
                ("security", _make_config("Security expert")),
                ("performance", _make_config("Performance expert")),
            ],
            context={},
            tool_registry_getter=lambda: [],
        )

        assert result.success
        assert result.rounds_completed == 3
        assert len(result.opinions) == 4
        assert "Both agree on A" in result.consensus_points[0]
        assert "Implement A" in result.action_items[0]
        assert result.total_duration_seconds > 0
        assert mock_emit.call_count == 3

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_all_phase1_experts_fail(self, mock_emit: AsyncMock) -> None:
        mgr = _make_manager([_fail(), _fail()])

        result = await run_council(
            manager=mgr,
            task_description="Review X",
            expert_configs=[("a", _make_config()), ("b", _make_config())],
            context={},
            tool_registry_getter=lambda: [],
        )

        assert not result.success
        assert "All experts failed" in result.error
        assert result.rounds_completed == 1

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_chair_failure(self, mock_emit: AsyncMock) -> None:
        spawn_results = [
            _ok(result="Analysis A"),
            _ok(result="Analysis B"),
            _ok(result="Cross A"),
            _ok(result="Cross B"),
            _fail(error="Chair model error"),
        ]
        mgr = _make_manager(spawn_results)

        result = await run_council(
            manager=mgr,
            task_description="Review X",
            expert_configs=[("a", _make_config()), ("b", _make_config())],
            context={},
            tool_registry_getter=lambda: [],
        )

        assert not result.success
        assert "Chair synthesis failed" in result.error
        assert len(result.opinions) == 4

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_custom_chair_config(self, mock_emit: AsyncMock) -> None:
        spawn_results = [
            _ok(result="A"), _ok(result="B"),
            _ok(result="CA"), _ok(result="CB"),
            _ok(result="### Consensus Points\n- OK\n### Divergences\n### Action Items\n- Do X"),
        ]
        mgr = _make_manager(spawn_results)

        custom_chair = SubagentConfig(
            system_prompt="You are a custom chair.",
            model="gpt-4o",
        )

        result = await run_council(
            manager=mgr,
            task_description="Review X",
            expert_configs=[("a", _make_config()), ("b", _make_config())],
            context={},
            tool_registry_getter=lambda: [],
            chair_config=custom_chair,
        )

        assert result.success
        chair_call = mgr.spawn_child.call_args_list[-1]
        actual_config = chair_call.kwargs.get("config") or chair_call[1].get("config")
        assert actual_config == custom_chair

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_multiple_cross_review_rounds(self, mock_emit: AsyncMock) -> None:
        spawn_results = [
            _ok(result="A1"), _ok(result="B1"),
            _ok(result="A-CR1"), _ok(result="B-CR1"),
            _ok(result="A-CR2"), _ok(result="B-CR2"),
            _ok(result="### Consensus Points\n- Yes\n### Divergences\n### Action Items\n"),
        ]
        mgr = _make_manager(spawn_results)

        result = await run_council(
            manager=mgr,
            task_description="Complex review",
            expert_configs=[("a", _make_config()), ("b", _make_config())],
            context={},
            tool_registry_getter=lambda: [],
            cross_review_rounds=2,
        )

        assert result.success
        assert result.rounds_completed == 4
        assert len(result.opinions) == 6
        assert mock_emit.call_count == 4

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_3_experts_council(self, mock_emit: AsyncMock) -> None:
        spawn_results = [
            _ok(result="Security analysis"),
            _ok(result="Performance analysis"),
            _ok(result="Cost analysis"),
            _ok(result="Security cross-review"),
            _ok(result="Performance cross-review"),
            _ok(result="Cost cross-review"),
            _ok(result="### Consensus Points\n- All agree on X\n### Divergences\n- Split on Y\n### Action Items\n- Do Z"),
        ]
        mgr = _make_manager(spawn_results)

        result = await run_council(
            manager=mgr,
            task_description="Payment system architecture",
            expert_configs=[
                ("security", _make_config("Security")),
                ("perf", _make_config("Performance")),
                ("cost", _make_config("Cost")),
            ],
            context={},
            tool_registry_getter=lambda: [],
        )

        assert result.success
        assert len(result.opinions) == 6
        assert len(result.consensus_points) == 1
        assert len(result.divergences) == 1
        assert len(result.action_items) == 1

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_cancellation_after_phase1(self, mock_emit: AsyncMock) -> None:
        spawn_results = [_ok(result="A"), _ok(result="B")]
        mgr = _make_manager(spawn_results)

        cancel_token = MagicMock()
        cancel_token.is_cancelled = False

        call_count = 0
        original_spawn = mgr.spawn_child.side_effect

        async def cancelling_spawn(*args: object, **kwargs: object) -> SubAgentResult:
            nonlocal call_count
            result = await original_spawn(*args, **kwargs)
            call_count += 1
            if call_count >= 2:
                cancel_token.is_cancelled = True
            return result

        mgr.spawn_child = AsyncMock(side_effect=cancelling_spawn)

        result = await run_council(
            manager=mgr,
            task_description="Review X",
            expert_configs=[("a", _make_config()), ("b", _make_config())],
            context={},
            tool_registry_getter=lambda: [],
            cancel_token=cancel_token,
        )

        assert not result.success
        assert "Cancelled" in result.error

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_partial_phase1_failure_continues(self, mock_emit: AsyncMock) -> None:
        spawn_results = [
            _ok(result="Expert 0 succeeded"),
            _fail(error="Expert 1 crashed"),
            _ok(result="Expert 0 cross-review"),
            _ok(result="Expert 1 cross-review"),
            _ok(result="### Consensus Points\n- Partial\n### Divergences\n### Action Items\n"),
        ]
        mgr = _make_manager(spawn_results)

        result = await run_council(
            manager=mgr,
            task_description="Review X",
            expert_configs=[("a", _make_config()), ("b", _make_config())],
            context={},
            tool_registry_getter=lambda: [],
        )

        assert result.success
        phase1_opinions = [o for o in result.opinions if o.round_num == 1]
        assert sum(1 for o in phase1_opinions if o.success) == 1

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_cross_review_rounds_clamped(self, mock_emit: AsyncMock) -> None:
        spawn_results = [
            _ok(result="A"), _ok(result="B"),
            _ok(result="CR1-A"), _ok(result="CR1-B"),
            _ok(result="CR2-A"), _ok(result="CR2-B"),
            _ok(result="CR3-A"), _ok(result="CR3-B"),
            _ok(result="### Consensus Points\n### Divergences\n### Action Items\n"),
        ]
        mgr = _make_manager(spawn_results)

        result = await run_council(
            manager=mgr,
            task_description="Review X",
            expert_configs=[("a", _make_config()), ("b", _make_config())],
            context={},
            tool_registry_getter=lambda: [],
            cross_review_rounds=10,
        )

        assert result.success
        assert result.rounds_completed == 5

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_dict_chair_result(self, mock_emit: AsyncMock) -> None:
        """Chair returning a dict instead of SubAgentResult is handled."""
        mgr = _make_manager([
            _ok(result="A"), _ok(result="B"),
            _ok(result="CA"), _ok(result="CB"),
        ])

        original_spawn = mgr.spawn_child.side_effect
        call_count = 0

        async def spawn_with_dict_chair(*args: object, **kwargs: object) -> SubAgentResult | dict:
            nonlocal call_count
            call_count += 1
            if call_count == 5:
                return {
                    "success": True,
                    "result": "### Consensus Points\n- OK\n### Divergences\n### Action Items\n",
                }
            return await original_spawn(*args, **kwargs)

        mgr.spawn_child = AsyncMock(side_effect=spawn_with_dict_chair)

        result = await run_council(
            manager=mgr,
            task_description="Review X",
            expert_configs=[("a", _make_config()), ("b", _make_config())],
            context={},
            tool_registry_getter=lambda: [],
        )

        assert result.success

    @pytest.mark.asyncio
    @patch(
        "myrm_agent_harness.agent.sub_agents._orchestrator_council._emit_council_phase",
        new_callable=AsyncMock,
    )
    async def test_custom_prompt_templates(self, mock_emit: AsyncMock) -> None:
        spawn_results = [
            _ok(result="A"), _ok(result="B"),
            _ok(result="CA"), _ok(result="CB"),
            _ok(result="### Consensus Points\n- OK\n### Divergences\n### Action Items\n"),
        ]
        mgr = _make_manager(spawn_results)

        custom_cr = "Custom cross-review: {other_opinions}"
        custom_chair = "Custom chair: {all_opinions}"

        result = await run_council(
            manager=mgr,
            task_description="Review X",
            expert_configs=[("a", _make_config()), ("b", _make_config())],
            context={},
            tool_registry_getter=lambda: [],
            cross_review_prompt_template=custom_cr,
            chair_prompt_template=custom_chair,
        )

        assert result.success
        cr_call = mgr.spawn_child.call_args_list[2]
        cr_desc = cr_call.kwargs.get("task_description") or cr_call[1].get("task_description", "")
        assert "Custom cross-review" in cr_desc
