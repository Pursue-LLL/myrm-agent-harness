import pytest
from myrm_agent_harness.agent.sub_agents.graph_triage import (
    BudgetCapConfig,
    BudgetStatus,
    ElasticConcurrencyReducer,
    ExecutionSpendState,
    GraphApplicabilityTriageGate,
    PartialNodeOutput,
    TaskComplexityCategory,
    TriageVerdict,
)
from myrm_agent_harness.agent.sub_agents.graph_triage.budget_guard import (
    PredictiveBudgetGuard,
)


@pytest.fixture
def triage_gate() -> GraphApplicabilityTriageGate:
    return GraphApplicabilityTriageGate()


@pytest.fixture
def budget_guard() -> PredictiveBudgetGuard:
    return PredictiveBudgetGuard()


@pytest.fixture
def elastic_reducer() -> ElasticConcurrencyReducer:
    return ElasticConcurrencyReducer()


def test_triage_simple_single_step(triage_gate: GraphApplicabilityTriageGate) -> None:
    # Test case 1: Fix typo
    prompt = "改一下错别字"
    decision = triage_gate.evaluate(prompt)
    assert decision.verdict == TriageVerdict.REJECT_TO_SINGLE_AGENT
    assert decision.category == TaskComplexityCategory.SIMPLE_SINGLE_STEP
    assert decision.estimated_tokens_saved > 0
    assert decision.estimated_speedup_ratio >= 2.0

    # Test case 2: Lookup single status
    prompt_en = "lookup single status"
    decision_en = triage_gate.evaluate(prompt_en)
    assert decision_en.verdict == TriageVerdict.REJECT_TO_SINGLE_AGENT
    assert decision_en.category == TaskComplexityCategory.SIMPLE_SINGLE_STEP


def test_triage_exploratory_conversation(triage_gate: GraphApplicabilityTriageGate) -> None:
    prompt = "针对电商搜索架构我们来头脑风暴一下，你觉得有哪些好的实践？"
    decision = triage_gate.evaluate(prompt)
    assert decision.verdict == TriageVerdict.REJECT_TO_CONVERSATIONAL
    assert decision.category == TaskComplexityCategory.EXPLORATORY_CHAT
    assert "保持单 Agent 交互模式" in decision.reason
    assert decision.estimated_tokens_saved >= 30_000


def test_triage_strictly_sequential(triage_gate: GraphApplicabilityTriageGate) -> None:
    prompt = "先抓取数据，然后清洗，接着训练，最后导出"
    subtasks = [
        {"id": "step1", "deps": []},
        {"id": "step2", "deps": ["step1"]},
        {"id": "step3", "deps": ["step2"]},
        {"id": "step4", "deps": ["step3"]},
    ]
    decision = triage_gate.evaluate(prompt, subtasks)
    assert decision.verdict == TriageVerdict.REJECT_TO_LINEAR_PIPELINE
    assert decision.category == TaskComplexityCategory.STRICTLY_SEQUENTIAL
    assert "保持轻量线性流水线模式" in decision.reason
    assert decision.features.max_dependency_depth == 4
    assert decision.features.independent_parallel_count == 1


def test_triage_parallel_heavyweight_admit(triage_gate: GraphApplicabilityTriageGate) -> None:
    prompt = "并行分析 3 个独立微服务的调用链路与依赖拓扑"
    subtasks = [
        {"id": "service_a", "deps": [], "heavy": True},
        {"id": "service_b", "deps": [], "heavy": True},
        {"id": "service_c", "deps": [], "heavy": True},
        {"id": "aggregator", "deps": ["service_a", "service_b", "service_c"]},
    ]
    decision = triage_gate.evaluate(prompt, subtasks)
    assert decision.verdict == TriageVerdict.ADMIT_GRAPH
    assert decision.category == TaskComplexityCategory.PARALLEL_HEAVYWEIGHT
    assert "准许激活多智能体图并发编排" in decision.reason
    assert decision.features.independent_parallel_count == 3


def test_predictive_budget_estimation_and_hard_cap_intercept(
    budget_guard: PredictiveBudgetGuard,
) -> None:
    cfg = BudgetCapConfig(max_tokens=100_000, max_cost_usd=1.0)

    # 1. Normal task within budget
    normal_est = budget_guard.estimate_budget(
        node_count=3,
        fanout_concurrency=3,
        prompt_tokens=1000,
        estimated_tokens_per_node=10_000,
        config=cfg,
    )
    assert not normal_est["is_circuit_broken"]
    assert normal_est["recommendation"] == "ALLOW"

    # 2. Heavy task exceeding hard cap (e.g. 15 nodes, 15000 tokens each = 225k tokens > 100k cap)
    heavy_est = budget_guard.estimate_budget(
        node_count=15,
        fanout_concurrency=8,
        prompt_tokens=2000,
        estimated_tokens_per_node=15_000,
        config=cfg,
    )
    assert heavy_est["is_circuit_broken"]
    assert "INTERCEPT" in str(heavy_est["recommendation"])


def test_runtime_spend_tracking_and_elastic_throttling(
    budget_guard: PredictiveBudgetGuard,
    elastic_reducer: ElasticConcurrencyReducer,
) -> None:
    session_id = "test-session-budget-1"
    cfg = BudgetCapConfig(
        max_tokens=100_000,
        max_cost_usd=2.0,
        warning_threshold_pct=0.3,
        critical_threshold_pct=0.1,
    )
    budget_guard.configure_session(session_id, cfg, initial_concurrency=6)

    # State 1: Healthy (spent 20,000, remaining 80%)
    s1 = budget_guard.check_and_update_spend(session_id, incremental_tokens=20_000)
    assert s1.budget_status == BudgetStatus.HEALTHY
    assert not s1.is_throttled
    assert elastic_reducer.calculate_concurrency(s1, requested_concurrency=6) == 6

    # State 2: Warning (spent another 55,000 -> total 75,000, remaining 25% <= 30%)
    s2 = budget_guard.check_and_update_spend(session_id, incremental_tokens=55_000)
    assert s2.budget_status == BudgetStatus.WARNING
    assert s2.is_throttled
    assert elastic_reducer.calculate_concurrency(s2, requested_concurrency=6) == 3

    # State 3: Critical (spent another 18,000 -> total 93,000, remaining 7% <= 10%)
    s3 = budget_guard.check_and_update_spend(session_id, incremental_tokens=18_000)
    assert s3.budget_status == BudgetStatus.CRITICAL
    assert s3.is_throttled
    assert not s3.is_circuit_broken
    assert elastic_reducer.calculate_concurrency(s3, requested_concurrency=6) == 1

    # State 4: Exhausted (spent another 10,000 -> total 103,000, exceeded cap)
    s4 = budget_guard.check_and_update_spend(session_id, incremental_tokens=10_000)
    assert s4.budget_status == BudgetStatus.EXHAUSTED
    assert s4.is_circuit_broken
    assert elastic_reducer.calculate_concurrency(s4, requested_concurrency=6) == 0


def test_graceful_partial_early_reduce(elastic_reducer: ElasticConcurrencyReducer) -> None:
    session_id = "test-session-reduce-1"
    spend_state = ExecutionSpendState(
        session_id=session_id,
        current_tokens=42_000,
        current_cost_usd=0.126,
        remaining_tokens=8_000,
        remaining_budget_pct=0.08,
        budget_status=BudgetStatus.CRITICAL,
        active_concurrency=1,
        is_throttled=True,
    )
    node_outputs = [
        PartialNodeOutput(
            node_id="parser",
            status="completed",
            result_summary="Parsed AST successfully with 12 modules.",
            tokens_used=15_000,
        ),
        PartialNodeOutput(
            node_id="linter",
            status="completed",
            result_summary="Found 0 fatal errors, 2 warnings.",
            tokens_used=27_000,
        ),
        PartialNodeOutput(
            node_id="optimizer",
            status="pending",
            result_summary="",
            tokens_used=0,
        ),
        PartialNodeOutput(
            node_id="deployer",
            status="pending",
            result_summary="",
            tokens_used=0,
        ),
    ]

    report = elastic_reducer.perform_graceful_early_reduce(
        session_id=session_id,
        spend_state=spend_state,
        node_outputs=node_outputs,
        total_planned_tokens=100_000,
    )

    assert report.session_id == session_id
    assert len(report.completed_nodes) == 2
    assert "parser" in report.completed_nodes
    assert "linter" in report.completed_nodes
    assert len(report.unexecuted_nodes) == 2
    assert report.tokens_spent == 42_000
    assert report.tokens_saved == 58_000
    assert report.delivery_confidence == 0.5
    assert "Graceful Early Reduce Triggered" in report.summary
    assert "Partial deliverable salvaged" in report.reason
