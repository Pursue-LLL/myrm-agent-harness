"""myrm_agent_harness/agent/sub_agents/graph_triage/budget_guard.py

[INPUT]
- (none — 标准库与内建依赖)

[OUTPUT]
- PredictiveBudgetGuard

[POS]
myrm_agent_harness/agent/sub_agents/graph_triage/budget_guard.py
"""

from myrm_agent_harness.agent.sub_agents.graph_triage.types import (
    BudgetCapConfig,
    BudgetStatus,
    ExecutionSpendState,
)


class PredictiveBudgetGuard:
    """Predictive budgeting and hard-cap circuit breaker for multi-agent graph execution.

    Pre-estimates token and cost usage before fan-out and actively monitors
    real-time consumption to prevent catastrophic run-away spending.
    """

    def __init__(self, default_config: BudgetCapConfig | None = None) -> None:
        self._config = default_config or BudgetCapConfig()
        self._sessions: dict[str, ExecutionSpendState] = {}
        self._session_configs: dict[str, BudgetCapConfig] = {}
        self._base_concurrency: dict[str, int] = {}

    def configure_session(
        self,
        session_id: str,
        config: BudgetCapConfig,
        initial_concurrency: int = 4,
    ) -> ExecutionSpendState:
        self._session_configs[session_id] = config
        self._base_concurrency[session_id] = max(1, initial_concurrency)
        state = ExecutionSpendState(
            session_id=session_id,
            current_tokens=0,
            current_cost_usd=0.0,
            remaining_tokens=config.max_tokens,
            remaining_budget_pct=1.0,
            budget_status=BudgetStatus.HEALTHY,
            active_concurrency=max(1, initial_concurrency),
            is_throttled=False,
            is_circuit_broken=False,
        )
        self._sessions[session_id] = state
        return state

    def estimate_budget(
        self,
        node_count: int,
        fanout_concurrency: int,
        prompt_tokens: int = 1_000,
        estimated_tokens_per_node: int = 15_000,
        cost_per_1k_tokens: float = 0.003,
        config: BudgetCapConfig | None = None,
    ) -> dict[str, float | int | bool | str]:
        cfg = config or self._config
        clamped_node_count = max(1, node_count)
        clamped_fanout = max(1, fanout_concurrency)

        # Total predicted tokens = prompt context + nodes * per_node_tokens + coordination overhead
        coordination_overhead = int(clamped_fanout * 1_500)
        total_estimated_tokens = prompt_tokens + (clamped_node_count * estimated_tokens_per_node) + coordination_overhead
        estimated_cost_usd = round((total_estimated_tokens / 1_000.0) * cost_per_1k_tokens, 4)

        exceeds_token_cap = total_estimated_tokens > cfg.max_tokens
        exceeds_cost_cap = estimated_cost_usd > cfg.max_cost_usd
        is_circuit_broken = exceeds_token_cap or exceeds_cost_cap

        recommendation = "ALLOW"
        if is_circuit_broken:
            recommendation = (
                f"INTERCEPT: Estimated {total_estimated_tokens} tokens (${estimated_cost_usd}) "
                f"exceeds hard cap of {cfg.max_tokens} tokens (${cfg.max_cost_usd})."
            )

        return {
            "total_estimated_tokens": total_estimated_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "max_tokens_cap": cfg.max_tokens,
            "max_cost_usd_cap": cfg.max_cost_usd,
            "is_circuit_broken": is_circuit_broken,
            "recommendation": recommendation,
        }

    def check_and_update_spend(
        self,
        session_id: str,
        incremental_tokens: int,
        incremental_cost_usd: float | None = None,
    ) -> ExecutionSpendState:
        cfg = self._session_configs.get(session_id, self._config)
        base_concurrency = self._base_concurrency.get(session_id, 4)

        if session_id not in self._sessions:
            self._sessions[session_id] = ExecutionSpendState(
                session_id=session_id,
                remaining_tokens=cfg.max_tokens,
                active_concurrency=base_concurrency,
            )

        current_state = self._sessions[session_id]

        new_total_tokens = current_state.current_tokens + max(0, incremental_tokens)
        cost_delta = (
            incremental_cost_usd
            if incremental_cost_usd is not None
            else round((max(0, incremental_tokens) / 1_000.0) * 0.003, 4)
        )
        new_total_cost = round(current_state.current_cost_usd + cost_delta, 4)

        remaining_tokens = max(0, cfg.max_tokens - new_total_tokens)
        remaining_budget_pct = round(remaining_tokens / float(cfg.max_tokens), 4)

        # Determine budget status
        if remaining_tokens <= 0 or new_total_cost >= cfg.max_cost_usd:
            status = BudgetStatus.EXHAUSTED
            active_concurrency = 0
            is_throttled = True
            is_circuit_broken = True
        elif remaining_budget_pct <= cfg.critical_threshold_pct:
            status = BudgetStatus.CRITICAL
            active_concurrency = 1
            is_throttled = True
            is_circuit_broken = False
        elif remaining_budget_pct <= cfg.warning_threshold_pct:
            status = BudgetStatus.WARNING
            active_concurrency = max(1, base_concurrency // 2)
            is_throttled = True
            is_circuit_broken = False
        else:
            status = BudgetStatus.HEALTHY
            active_concurrency = base_concurrency
            is_throttled = False
            is_circuit_broken = False

        updated_state = ExecutionSpendState(
            session_id=session_id,
            current_tokens=new_total_tokens,
            current_cost_usd=new_total_cost,
            remaining_tokens=remaining_tokens,
            remaining_budget_pct=remaining_budget_pct,
            budget_status=status,
            active_concurrency=active_concurrency,
            is_throttled=is_throttled,
            is_circuit_broken=is_circuit_broken,
        )
        self._sessions[session_id] = updated_state
        return updated_state

    def get_state(self, session_id: str) -> ExecutionSpendState:
        if session_id in self._sessions:
            return self._sessions[session_id]
        return ExecutionSpendState(session_id=session_id)

    def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._session_configs.pop(session_id, None)
        self._base_concurrency.pop(session_id, None)
