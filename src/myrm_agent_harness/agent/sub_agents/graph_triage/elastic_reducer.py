"""myrm_agent_harness/agent/sub_agents/graph_triage/elastic_reducer.py

[INPUT]
- (none — 标准库与内建依赖)

[OUTPUT]
- ElasticConcurrencyReducer

[POS]
myrm_agent_harness/agent/sub_agents/graph_triage/elastic_reducer.py
"""

from myrm_agent_harness.agent.sub_agents.graph_triage.types import (
    BudgetStatus,
    ExecutionSpendState,
    PartialNodeOutput,
    PartialReduceReport,
)


class ElasticConcurrencyReducer:
    """Adaptive concurrency throttling and graceful partial early reduce engine.

    Dynamically modulates fan-out parallel degree based on remaining budget,
    and executes partial early synthesis upon critical budget depletion,
    preventing catastrophic all-or-nothing task collapse.
    """

    def calculate_concurrency(
        self,
        spend_state: ExecutionSpendState,
        requested_concurrency: int = 4,
    ) -> int:
        clamped_req = max(1, requested_concurrency)

        if spend_state.is_circuit_broken or spend_state.budget_status == BudgetStatus.EXHAUSTED:
            return 0

        if spend_state.budget_status == BudgetStatus.CRITICAL:
            return 1

        if spend_state.budget_status == BudgetStatus.WARNING:
            return max(1, clamped_req // 2)

        return clamped_req

    def perform_graceful_early_reduce(
        self,
        session_id: str,
        spend_state: ExecutionSpendState,
        node_outputs: list[PartialNodeOutput],
        total_planned_tokens: int,
    ) -> PartialReduceReport:
        completed_nodes: list[str] = []
        unexecuted_nodes: list[str] = []
        synthesized_parts: list[str] = []

        total_nodes = len(node_outputs)
        for node in node_outputs:
            if node.status == "completed":
                completed_nodes.append(node.node_id)
                summary_text = node.result_summary.strip() or f"Node {node.node_id} executed successfully."
                synthesized_parts.append(f"[{node.node_id}]: {summary_text}")
            else:
                unexecuted_nodes.append(node.node_id)

        tokens_spent = spend_state.current_tokens
        tokens_saved = max(0, total_planned_tokens - tokens_spent)
        delivery_confidence = round(len(completed_nodes) / max(1, total_nodes), 2)

        summary_header = (
            f"Graceful Early Reduce Triggered ({spend_state.budget_status.upper()}). "
            f"Delivered {len(completed_nodes)}/{total_nodes} nodes with {tokens_saved} tokens preserved."
        )
        full_summary = f"{summary_header}\n" + "\n".join(synthesized_parts)

        reason = (
            f"Triggered due to budget constraint. Current remaining budget: "
            f"{round(spend_state.remaining_budget_pct * 100, 1)}%. Partial deliverable salvaged."
        )

        return PartialReduceReport(
            session_id=session_id,
            summary=full_summary,
            completed_nodes=completed_nodes,
            unexecuted_nodes=unexecuted_nodes,
            tokens_spent=tokens_spent,
            tokens_saved=tokens_saved,
            delivery_confidence=delivery_confidence,
            reason=reason,
        )
