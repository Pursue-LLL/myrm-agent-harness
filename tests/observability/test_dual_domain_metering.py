"""
[INPUT]: dual_domain_metering models and ledger.
[OUTPUT]: Pytest verification for DualDomainMeteringLedger and reconciliation statements.
[POS]: myrm-agent-harness/tests/observability/test_dual_domain_metering.py
"""

import pytest

from myrm_agent_harness.observability.dual_domain_metering import (
    DomainMeteringRecord,
    DualDomainMeteringLedger,
    MeteringDomain,
    ReconciliationStatement,
    SessionDualDomainSummary,
    ThreeDimensionalCost,
    get_default_dual_domain_ledger,
)


def test_dual_domain_metering_flow_and_summary() -> None:
    ledger = DualDomainMeteringLedger()

    # 1. Record Gateway Domain (LLM Prompt & Tokens)
    rec_gw = ledger.record_metering(
        session_id="sess-corp-88",
        domain=MeteringDomain.GATEWAY_DOMAIN,
        operation_name="llm_chat_completion",
        resource_units=3500.0,  # 3500 tokens
        cost_breakdown=ThreeDimensionalCost(
            model_token_cost_usd=0.0105,
            sandbox_compute_cost_usd=0.0,
            thirdparty_tool_cost_usd=0.0,
        ),
        billable=True,
        policy_note="Gateway LLM Token Metering",
    )
    assert rec_gw.domain == MeteringDomain.GATEWAY_DOMAIN
    assert rec_gw.cost_breakdown.total_cost_usd == 0.0105

    # 2. Record Sandbox Domain (Container CPU/RAM)
    rec_sb = ledger.record_metering(
        session_id="sess-corp-88",
        domain=MeteringDomain.SANDBOX_DOMAIN,
        operation_name="python_script_execution",
        resource_units=12.5,  # 12.5 seconds CPU
        cost_breakdown=ThreeDimensionalCost(
            model_token_cost_usd=0.0,
            sandbox_compute_cost_usd=0.0025,
            thirdparty_tool_cost_usd=0.0,
        ),
        billable=True,
        policy_note="Sandbox Container Compute Metering",
    )
    assert rec_sb.domain == MeteringDomain.SANDBOX_DOMAIN
    assert rec_sb.cost_breakdown.total_cost_usd == 0.0025

    # 3. Record Third-party External Tool (Brave Search)
    rec_tool = ledger.record_metering(
        session_id="sess-corp-88",
        domain=MeteringDomain.SANDBOX_DOMAIN,
        operation_name="brave_web_search",
        resource_units=1.0,  # 1 query
        cost_breakdown=ThreeDimensionalCost(
            model_token_cost_usd=0.0,
            sandbox_compute_cost_usd=0.0,
            thirdparty_tool_cost_usd=0.005,
        ),
        billable=True,
        policy_note="External MCP Search Query",
    )
    assert rec_tool.cost_breakdown.total_cost_usd == 0.005

    # 4. Compute Session Summary
    summary = ledger.get_session_summary("sess-corp-88")
    assert summary.session_id == "sess-corp-88"
    assert summary.total_operations == 3
    assert summary.gateway_ops_count == 1
    assert summary.sandbox_ops_count == 2
    assert summary.gateway_token_cost_usd == pytest.approx(0.0105)
    assert summary.sandbox_compute_cost_usd == pytest.approx(0.0025)
    assert summary.thirdparty_tool_cost_usd == pytest.approx(0.005)
    assert summary.total_cost_usd == pytest.approx(0.018)
    assert summary.gateway_cost_ratio == pytest.approx(0.0105 / 0.018, abs=1e-3)

    # 5. Generate Tamper-Proof Reconciliation Statement
    statement = ledger.generate_reconciliation_statement("sess-corp-88")
    assert statement.session_id == "sess-corp-88"
    assert len(statement.records) == 3
    assert len(statement.integrity_sha256) == 64  # Valid SHA-256 length

    # Validate SHA-256 matches exact recalculation
    recalc_hash = ReconciliationStatement.compute_sha256("sess-corp-88", statement.summary, statement.records)
    assert statement.integrity_sha256 == recalc_hash

    # 6. List statements
    stmts = ledger.list_statements()
    assert len(stmts) == 1
    assert stmts[0].statement_id == statement.statement_id


def test_default_ledger_singleton_and_reset() -> None:
    l1 = get_default_dual_domain_ledger()
    l2 = get_default_dual_domain_ledger()
    assert l1 is l2

    l1.record_metering(
        session_id="sess-tmp",
        domain=MeteringDomain.GATEWAY_DOMAIN,
        operation_name="ping",
        resource_units=1.0,
        cost_breakdown=ThreeDimensionalCost(),
    )
    assert l1.get_session_summary("sess-tmp").total_operations == 1

    l1.reset()
    assert l1.get_session_summary("sess-tmp").total_operations == 0
    assert len(l1.list_statements()) == 0
