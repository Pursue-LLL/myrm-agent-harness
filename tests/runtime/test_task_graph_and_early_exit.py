"""Unit tests for Task Graph Critical Path Pruning and Early Exit Optimization Suite."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.runtime.task_graph import (
    DAGDependencyCompiler,
    EarlyExitEvaluator,
    ParallelDAGExecutor,
    TaskNode,
    TaskStatus,
)


def test_dag_dependency_compiler_wave_grouping() -> None:
    """Verify compiler partitions DAG into parallel waves and handles cyclic dependencies."""
    # Graph:
    # A (root), B (root)
    # C depends on A
    # D depends on A and B
    # E depends on C and D
    tasks = [
        TaskNode(task_id="A", tool_name="fetch_user"),
        TaskNode(task_id="B", tool_name="fetch_product"),
        TaskNode(task_id="C", tool_name="query_orders", dependencies=("A",)),
        TaskNode(task_id="D", tool_name="check_inventory", dependencies=("A", "B")),
        TaskNode(task_id="E", tool_name="render_invoice", dependencies=("C", "D")),
    ]

    compilation = DAGDependencyCompiler.compile_waves(tasks)

    assert compilation.has_cycle is False
    assert compilation.critical_path_length == 3  # Wave 0 (A,B) -> Wave 1 (C,D) -> Wave 2 (E)
    assert len(compilation.waves) == 3

    assert set(compilation.waves[0].task_ids) == {"A", "B"}
    assert set(compilation.waves[1].task_ids) == {"C", "D"}
    assert set(compilation.waves[2].task_ids) == {"E"}

    # Test cyclic dependency fallback
    tasks_with_cycle = [
        TaskNode(task_id="X", tool_name="tool_x", dependencies=("Y",)),
        TaskNode(task_id="Y", tool_name="tool_y", dependencies=("X",)),
    ]
    comp_cycle = DAGDependencyCompiler.compile_waves(tasks_with_cycle)
    assert comp_cycle.has_cycle is True
    assert len(comp_cycle.waves) > 0  # Fallback sequential waves generated


@pytest.mark.asyncio
async def test_parallel_dag_executor_latency_compression() -> None:
    """Verify independent tasks in the same wave execute concurrently, cutting latency."""
    # 3 independent tasks, each takes 0.05s
    tasks = [
        TaskNode(task_id="t1", tool_name="tool_a"),
        TaskNode(task_id="t2", tool_name="tool_b"),
        TaskNode(task_id="t3", tool_name="tool_c"),
    ]

    async def mock_tool_runner(name: str, params: dict[str, str]) -> str:
        await asyncio.sleep(0.05)
        return f"Result of {name}"

    executor = ParallelDAGExecutor(mock_tool_runner)
    metrics = await executor.execute_graph(tasks)

    # 3 tasks * 0.05s = 0.15s serial time.
    # Parallel execution wall time should be ~0.05s.
    assert metrics.total_tasks_executed == 3
    assert metrics.total_waves == 1
    assert metrics.parallel_duration_s < 0.12  # Well under serial 0.15s
    assert metrics.latency_reduction_ratio > 40.0

    for t in tasks:
        assert t.status == TaskStatus.COMPLETED
        assert "Result of" in t.result


@pytest.mark.asyncio
async def test_parallel_dag_executor_dependency_failure_short_circuit() -> None:
    """Verify downstream tasks are automatically skipped when upstream dependencies fail."""
    tasks = [
        TaskNode(task_id="step_1", tool_name="faulty_tool"),
        TaskNode(task_id="step_2", tool_name="dependent_tool", dependencies=("step_1",)),
    ]

    step_2_invoked = False

    async def mock_runner(name: str, params: dict[str, str]) -> str:
        nonlocal step_2_invoked
        if name == "faulty_tool":
            raise RuntimeError("Database connection timed out")
        if name == "dependent_tool":
            step_2_invoked = True
            return "ok"
        return "default"

    executor = ParallelDAGExecutor(mock_runner)
    await executor.execute_graph(tasks)

    # Invariant: step_1 failed, step_2 must be skipped without invocation
    assert tasks[0].status == TaskStatus.FAILED
    assert tasks[1].status == TaskStatus.SKIPPED_DEPENDENCY_FAILED
    assert step_2_invoked is False
    assert "was not completed successfully" in tasks[1].error_msg


def test_early_exit_evaluator_aspect_sufficiency_and_max_ceiling() -> None:
    """Verify early exit evaluator trips upon factual completeness and respects max iterations."""
    evaluator = EarlyExitEvaluator(
        required_aspects=("flight_price", "hotel_availability"),
        max_iterations=4,
    )

    # Iteration 1: Only flight_price collected -> continue
    v1 = evaluator.evaluate_early_exit(current_iteration=1, gathered_aspects={"flight_price"})
    assert v1.should_exit is False
    assert "missing required aspects" in v1.reason

    # Iteration 2: Both collected -> trigger early exit
    v2 = evaluator.evaluate_early_exit(
        current_iteration=2,
        gathered_aspects={"flight_price", "hotel_availability"},
    )
    assert v2.should_exit is True
    assert "Information sufficiency satisfied" in v2.reason
    assert "hotel_availability" in v2.covered_aspects

    # Iteration 4: Hard iteration ceiling reached -> trigger early exit
    v4 = evaluator.evaluate_early_exit(
        current_iteration=4,
        gathered_aspects={"flight_price"},
    )
    assert v4.should_exit is True
    assert "Exceeded maximum reasoning iterations ceiling" in v4.reason


def test_in_flight_high_purity_pruning_and_markdown() -> None:
    """Verify in-flight pruning strips HTML/whitespace and dashboard card renders properly."""
    raw_html = """
    <html>
        <body>
            <nav><div>Home | About | Contact</div></nav>
            <div class="content">
                The current exchange rate for USD to CNY is 7.2341 as of today.
                Lots of unrelated boilerplates and legal disclaimers follow here...
            </div>
        </body>
    </html>
    """

    pruned = EarlyExitEvaluator.prune_context_high_purity(
        raw_text=raw_html,
        focus_keywords=("exchange rate", "7.2341"),
        max_chars=80,
    )

    assert "<nav>" not in pruned
    assert "exchange rate" in pruned
    assert len(pruned) <= 90

    # Markdown rendering verification
    from myrm_agent_harness.runtime.task_graph import DAGExecutionMetrics

    metrics = DAGExecutionMetrics(
        total_tasks_executed=1,
        total_waves=1,
        parallel_duration_s=0.05,
        simulated_serial_duration_s=0.05,
        latency_reduction_ratio=0.0,
    )
    card = EarlyExitEvaluator.render_optimization_markdown(metrics)

    assert "### ⚡ 任务图关键路径裁切与早停自收敛看板" in card
    assert "> [!TIP]" in card
