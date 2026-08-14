"""Tests for DW PTC llm_query / llm_query_batched tools and preflight counting."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import tool as lc_tool

from myrm_agent_harness.agent.dynamic_workflow.llm_query_tool import (
    _MAX_BATCH_QUERIES,
    LlmQueryBatchedTool,
    LlmQueryTool,
)
from myrm_agent_harness.agent.dynamic_workflow.preflight import (
    count_llm_query_calls,
    estimate_workflow_cost,
    format_plan_preview,
)
from myrm_agent_harness.agent.dynamic_workflow.tools import (
    DEFAULT_MAX_CONCURRENT_SPAWNS,
)
from myrm_agent_harness.toolkits.code_execution.ptc.stub_generator import (
    generate_stubs,
)


class _FakeResponse:
    def __init__(self, content: str, usage: dict[str, int]) -> None:
        self.content = content
        self.usage_metadata = usage


def _make_tool(use_batched: bool = False) -> LlmQueryTool | LlmQueryBatchedTool:
    parent = MagicMock()
    parent.model_resolver = None
    parent.llm = AsyncMock()
    cls = LlmQueryBatchedTool if use_batched else LlmQueryTool
    return cls(parent_agent=parent)


# ---------------------------------------------------------------------------
# stub_generator: array / object param serialization
# ---------------------------------------------------------------------------


@lc_tool
def mock_batch(prompts: list[str], system: str = "") -> str:
    """Process a list of prompts."""
    return f"got {len(prompts)} prompts"


@lc_tool
def mock_meta(config: dict, label: str) -> str:
    """Merge config and label."""
    return f"{label}:{config}"


class TestStubGeneratorArrayParams:
    def test_list_param_gets_list_type_hint(self) -> None:
        source = generate_stubs([mock_batch])
        assert "def mock_batch(prompts: list" in source

    def test_list_param_json_loads_serialization(self) -> None:
        source = generate_stubs([mock_batch])
        assert "json.loads(prompts)" in source

    def test_dict_param_gets_dict_type_hint(self) -> None:
        source = generate_stubs([mock_meta])
        assert "config: dict" in source
        assert "json.loads(config)" in source

    def test_generated_source_is_valid_python(self) -> None:
        source = generate_stubs([mock_batch, mock_meta])
        compile(source, "<stubs>", "exec")

    def test_optional_scalar_params_keep_types(self) -> None:
        from unittest.mock import MagicMock

        from myrm_agent_harness.agent.dynamic_workflow.llm_query_tool import (
            LlmQueryTool,
        )

        source = generate_stubs([LlmQueryTool(parent_agent=MagicMock())])
        assert "max_tokens: int = None" in source
        assert "temperature: float = None" in source
        assert "max_tokens is not None" in source

    def test_multiple_required_params_preserve_schema_order(self) -> None:
        """Multiple required params must not be reversed in the generated signature."""

        @lc_tool
        def mock_two(a: str, b: str) -> str:
            """Two required string params."""
            return a + b

        source = generate_stubs([mock_two])
        assert "def mock_two(a: str, b: str)" in source
        assert "def mock_two(b: str, a: str)" not in source


# ---------------------------------------------------------------------------
# preflight: llm_query call counting + cost estimation
# ---------------------------------------------------------------------------


class TestPreflightLlmQueryCounting:
    def test_counts_single_and_batched_separately(self) -> None:
        script = (
            "import myrm_tools\n"
            "myrm_tools.llm_query(prompt='summarize')\n"
            "myrm_tools.llm_query_batched(prompts=['a', 'b'])\n"
        )
        single, batched = count_llm_query_calls(script)
        assert single == 1
        assert batched == 1

    def test_spawn_pattern_not_counted_as_llm_query(self) -> None:
        script = "myrm_tools.spawn_subagent(task_id='t')\n"
        assert count_llm_query_calls(script) == (0, 0)

    def test_format_plan_preview_shows_llm_query_line(self) -> None:
        review = MagicMock()
        review.spawn_count = 1
        review.estimated_cost_usd = 0.01
        review.remaining_budget_usd = 5.0
        review.cost_status = "estimated"
        review.llm_query_single_calls = 1
        review.llm_query_batched_calls = 2
        review.script_code = "print(1)"
        preview = format_plan_preview(review)
        assert "1 direct AI call(s)" in preview
        assert "2 parallel batch(es) of AI calls" in preview
        assert "Estimate is approximate" in preview
        assert f"with up to {DEFAULT_MAX_CONCURRENT_SPAWNS} at a time" in preview

    def test_format_plan_preview_omits_llm_query_line_when_no_calls(self) -> None:
        review = MagicMock()
        review.spawn_count = 1
        review.estimated_cost_usd = None
        review.remaining_budget_usd = None
        review.cost_status = "no_spawns"
        review.llm_query_single_calls = 0
        review.llm_query_batched_calls = 0
        review.script_code = "print(1)"
        preview = format_plan_preview(review)
        assert "direct AI call(s)" not in preview
        assert "parallel batch(es)" not in preview
        assert "Estimate is approximate" not in preview
        assert "Cost estimate unavailable" in preview


@patch(
    "myrm_agent_harness.agent.dynamic_workflow.preflight._estimate_llm_query_cost",
    return_value=(0.05, "estimated"),
)
@pytest.mark.asyncio
async def test_estimate_workflow_cost_combines_spawn_and_llm_query(
    mock_llm_cost: MagicMock,
) -> None:
    parent = MagicMock()
    catalog = AsyncMock()
    from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

    catalog.resolve.return_value = SubagentConfig(
        system_prompt="sub",
        max_cost_usd=1.0,
    )

    cost, _remaining, status = await estimate_workflow_cost(parent, catalog, 2, "audit", llm_query_calls=(3, 1))
    assert cost == pytest.approx(2.05)
    assert status == "configured_max_cost"
    mock_llm_cost.assert_called_once_with(parent, 3, 1)


@patch(
    "myrm_agent_harness.agent.dynamic_workflow.preflight._estimate_llm_query_cost",
    return_value=(0.04, "estimated"),
)
@pytest.mark.asyncio
async def test_estimate_workflow_cost_llm_query_only(
    mock_llm_cost: MagicMock,
) -> None:
    cost, _remaining, status = await estimate_workflow_cost(MagicMock(), None, 0, "summarize", llm_query_calls=(2, 0))
    assert cost == pytest.approx(0.04)
    assert status == "estimated"


@patch(
    "myrm_agent_harness.agent.dynamic_workflow.preflight._estimate_llm_query_cost",
    return_value=(None, "model_cost_unavailable"),
)
@pytest.mark.asyncio
async def test_estimate_workflow_cost_llm_query_unavailable_falls_back_to_spawn(
    mock_llm_cost: MagicMock,
) -> None:
    parent = MagicMock()
    catalog = AsyncMock()
    from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

    catalog.resolve.return_value = SubagentConfig(
        system_prompt="sub",
        max_cost_usd=0.5,
    )
    cost, _remaining, status = await estimate_workflow_cost(parent, catalog, 1, "task", llm_query_calls=(1, 0))
    assert cost == pytest.approx(0.5)
    assert status == "configured_max_cost"


# ---------------------------------------------------------------------------
# LlmQueryTool
# ---------------------------------------------------------------------------


class TestLlmQueryTool:
    @pytest.mark.asyncio
    async def test_single_query_success_without_manual_usage_recording(self) -> None:
        tool = _make_tool()
        response = _FakeResponse(
            "answer",
            {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        tool.parent_agent.llm.ainvoke.return_value = response

        result = await tool._arun(prompt="q")

        assert result["success"] is True
        assert result["result"] == "answer"
        # Token accounting moved to the ChatLiteLLM adapter (non-streaming path);
        # the tool must not double-record via its own usage extraction.
        assert not hasattr(tool, "_record_usage")

    @pytest.mark.asyncio
    async def test_single_query_failure_is_isolated(self) -> None:
        tool = _make_tool()
        tool.parent_agent.llm.ainvoke.side_effect = RuntimeError("boom")

        with patch("myrm_agent_harness.agent.dynamic_workflow.llm_query_tool.record_token_error") as mock_error:
            result = await tool._arun(prompt="q")
        assert result["success"] is False
        assert "boom" in result["error"]
        mock_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancelled_returns_error_without_calling_llm(self) -> None:
        token = MagicMock()
        token.is_cancelled = True
        tool = LlmQueryTool(parent_agent=MagicMock(), cancel_token=token)
        result = await tool._arun(prompt="q")
        assert result["success"] is False
        assert "cancelled" in result["error"].lower()
        tool.parent_agent.llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_tokens_and_temperature_forwarded(self) -> None:
        tool = _make_tool()
        tool.parent_agent.llm.ainvoke.return_value = _FakeResponse(
            "ok", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        )
        await tool._arun(prompt="q", max_tokens=512, temperature=0.2)
        kwargs = tool.parent_agent.llm.ainvoke.call_args[1]
        assert kwargs["max_tokens"] == 512
        assert kwargs["temperature"] == 0.2

    @pytest.mark.asyncio
    async def test_budget_exhausted_blocks_call(self) -> None:
        tool = _make_tool()
        checker = MagicMock()
        checker.get_remaining_budget.return_value = 0.0
        tool.parent_agent.token_tracker = MagicMock()
        tool.parent_agent.token_tracker.budget_checker = checker
        result = await tool._arun(prompt="q")
        assert result["success"] is False
        assert "budget" in result["error"].lower()
        tool.parent_agent.llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_budget_not_exhausted_allows_call(self) -> None:
        tool = _make_tool()
        checker = MagicMock()
        checker.get_remaining_budget.return_value = 5.0
        tool.parent_agent.token_tracker = MagicMock()
        tool.parent_agent.token_tracker.budget_checker = checker
        tool.parent_agent.llm.ainvoke.return_value = _FakeResponse(
            "ok", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        )
        result = await tool._arun(prompt="q")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_unparsable_usage_metadata_does_not_break_call(self) -> None:
        tool = _make_tool()
        tool.parent_agent.llm.ainvoke.return_value = _FakeResponse(
            "ok", {"input_tokens": "nan", "output_tokens": "x", "total_tokens": "y"}
        )
        result = await tool._arun(prompt="q")
        assert result["success"] is True
        assert result["result"] == "ok"

    @pytest.mark.asyncio
    async def test_none_content_returns_empty_string(self) -> None:
        tool = _make_tool()
        tool.parent_agent.llm.ainvoke.return_value = MagicMock(content=None)
        result = await tool._arun(prompt="q")
        assert result["success"] is True
        assert result["result"] == ""

    @pytest.mark.asyncio
    async def test_reasoning_model_falls_back_to_reasoning_content(self) -> None:
        """DeepSeek-R1 / OpenAI o-series return content=None and put the
        answer in additional_kwargs['reasoning_content']."""
        tool = _make_tool()
        response = _FakeResponse(None, {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
        response.additional_kwargs = {"reasoning_content": "reasoned answer"}
        tool.parent_agent.llm.ainvoke.return_value = response
        result = await tool._arun(prompt="q")
        assert result["success"] is True
        assert result["result"] == "reasoned answer"

    @pytest.mark.asyncio
    async def test_anthropic_block_list_extracts_text(self) -> None:
        """Anthropic returns content as [{'type': 'text', 'text': '...'}]."""
        tool = _make_tool()
        response = _FakeResponse(
            [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}],
            {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        tool.parent_agent.llm.ainvoke.return_value = response
        result = await tool._arun(prompt="q")
        assert result["success"] is True
        assert result["result"] == "hello world"

    @pytest.mark.asyncio
    async def test_anthropic_empty_text_blocks_fall_back_to_reasoning(self) -> None:
        """Blocks with empty/missing text must not leak the list repr; the
        answer falls back to reasoning_content when present."""
        tool = _make_tool()
        response = _FakeResponse(
            [{"type": "text", "text": ""}],
            {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        response.additional_kwargs = {"reasoning_content": "reasoned answer"}
        tool.parent_agent.llm.ainvoke.return_value = response
        result = await tool._arun(prompt="q")
        assert result["success"] is True
        assert result["result"] == "reasoned answer"


# ---------------------------------------------------------------------------
# LlmQueryBatchedTool
# ---------------------------------------------------------------------------


class TestLlmQueryBatchedTool:
    @pytest.mark.asyncio
    async def test_batched_preserves_order(self) -> None:
        tool = _make_tool(use_batched=True)
        tool.parent_agent.llm.ainvoke.side_effect = [
            _FakeResponse("first", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}),
            _FakeResponse("second", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}),
        ]
        result = await tool._arun(prompts=["a", "b"])
        assert result["success"] is True
        assert result["failed"] == 0
        assert [r["result"] for r in result["results"]] == ["first", "second"]

    @pytest.mark.asyncio
    async def test_batched_isolates_per_prompt_failure(self) -> None:
        tool = _make_tool(use_batched=True)
        tool.parent_agent.llm.ainvoke.side_effect = [
            _FakeResponse("ok", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}),
            RuntimeError("boom"),
            _FakeResponse("ok2", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}),
        ]
        result = await tool._arun(prompts=["a", "b", "c"])
        assert result["success"] is True
        assert result["failed"] == 1
        assert [r["success"] for r in result["results"]] == [True, False, True]

    @pytest.mark.asyncio
    async def test_batched_empty_prompts(self) -> None:
        tool = _make_tool(use_batched=True)
        result = await tool._arun(prompts=[])
        assert result["success"] is True
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_batched_oversize_rejected(self) -> None:
        tool = _make_tool(use_batched=True)
        result = await tool._arun(prompts=["x"] * (_MAX_BATCH_QUERIES + 1))
        assert result["success"] is False
        assert "Too many prompts" in result["error"]

    @pytest.mark.asyncio
    async def test_batched_concurrency_limited_by_semaphore(self) -> None:
        tool = _make_tool(use_batched=True)
        tool.parent_agent.llm.ainvoke.return_value = _FakeResponse(
            "r", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        )
        result = await tool._arun(prompts=["a", "b", "c"], max_concurrent=2)
        assert result["failed"] == 0
        assert len(result["results"]) == 3

    @pytest.mark.asyncio
    async def test_batched_resolves_llm_once(self) -> None:
        """A batch must resolve the shared LLM once, not once per prompt."""
        tool = _make_tool(use_batched=True)
        tool.parent_agent.llm.ainvoke.side_effect = [
            _FakeResponse("a", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}),
            _FakeResponse("b", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}),
            _FakeResponse("c", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}),
        ]
        with patch(
            "myrm_agent_harness.agent.dynamic_workflow.llm_query_tool.LlmQueryTool._resolve_llm",
            autospec=True,
        ) as mock_resolve:
            mock_resolve.return_value = tool.parent_agent.llm
            result = await tool._arun(prompts=["a", "b", "c"])
        assert mock_resolve.call_count == 1
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_batched_budget_exhausted_blocks_batch(self) -> None:
        tool = _make_tool(use_batched=True)
        checker = MagicMock()
        checker.get_remaining_budget.return_value = 0.0
        tool.parent_agent.token_tracker = MagicMock()
        tool.parent_agent.token_tracker.budget_checker = checker
        result = await tool._arun(prompts=["a", "b"])
        assert result["success"] is False
        assert "budget" in result["error"].lower()
        tool.parent_agent.llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_batched_unparsable_usage_metadata_keeps_other_results(self) -> None:
        tool = _make_tool(use_batched=True)
        good = _FakeResponse("ok", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
        bad = _FakeResponse("bad", {"input_tokens": "nan", "output_tokens": "x", "total_tokens": "y"})
        tool.parent_agent.llm.ainvoke.side_effect = [good, bad]
        result = await tool._arun(prompts=["a", "b"])
        assert result["success"] is True
        assert result["failed"] == 0
        assert [r["result"] for r in result["results"]] == ["ok", "bad"]


# ---------------------------------------------------------------------------
# PTC end-to-end: stub list param → RPC → dispatcher → tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ptc_batched_stub_passes_list_to_tool() -> None:
    """A PTC script calling myrm_tools.llm_query_batched with a list must
    serialize the list through the RPC layer and dispatch it intact."""
    from langchain_core.messages import AIMessage

    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionContext,
    )
    from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
        inject_ptc_for_python_execution,
    )
    from tests.toolkits.code_execution._executor_stub import InProcessExecutor

    async def fake_ainvoke(messages, **kwargs) -> AIMessage:
        prompt = messages[-1].content
        return AIMessage(
            content=f"reply:{prompt}",
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        )

    parent = MagicMock()
    parent.model_resolver = None
    parent.llm = AsyncMock()
    parent.llm.ainvoke.side_effect = fake_ainvoke
    tool = LlmQueryBatchedTool(parent_agent=parent)

    script = 'import myrm_tools\nresult = myrm_tools.llm_query_batched(prompts=["q1", "q2"])\nprint(result)'
    context = ExecutionContext(code=script, timeout=30)
    executor = InProcessExecutor()
    result = await inject_ptc_for_python_execution(context, executor, [tool])
    assert result.success, result.stderr
    assert '"success": true' in (result.stdout or "")
    assert "reply:q1" in (result.stdout or "")
    assert "reply:q2" in (result.stdout or "")
