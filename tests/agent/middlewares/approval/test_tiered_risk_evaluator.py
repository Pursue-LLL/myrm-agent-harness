"""Unit tests for TieredRiskEvaluator (Level 1 Read, Level 2 Write, Level 3 High-Risk).

[INPUT]
- TieredRiskEvaluator, RiskTier, TieredRiskEvaluation from myrm_agent_harness.agent.middlewares.approval

[OUTPUT]
- Pytest unit tests verifying three-tier risk classification, dry-run simulation, and NEED_CONFIRMATION brake

[POS]
Unit test suite for Item 29 TieredRiskHitlConfirmationModalAndDryRunPreviewGate.
File length < 180 lines. Zero `Any`.
"""

from myrm_agent_harness.agent.middlewares.approval import TieredRiskEvaluator


def test_level_1_read_operations_fast_pass() -> None:
    evaluator = TieredRiskEvaluator()

    # read_file
    res1 = evaluator.evaluate("read_file", {"path": "/workspace/README.md"})
    assert res1.tier == "READ"
    assert res1.need_confirmation is False
    assert res1.suggested_action == "pass"
    assert res1.target_entity == "/workspace/README.md"
    assert res1.supports_dry_run is False

    # list_directory
    res2 = evaluator.evaluate("list_directory", {"path": "/workspace/src"})
    assert res2.tier == "READ"
    assert res2.need_confirmation is False

    # query_database
    res3 = evaluator.evaluate("query_database", {"sql": "SELECT * FROM users"})
    assert res3.tier == "READ"
    assert res3.need_confirmation is False


def test_level_2_write_operations_summary_and_dry_run() -> None:
    evaluator = TieredRiskEvaluator()

    # Normal write
    res1 = evaluator.evaluate(
        "write_to_file",
        {
            "target_file": "/workspace/config.json",
            "content": '{"version": "1.0"}',
        },
    )
    assert res1.tier == "WRITE"
    assert res1.need_confirmation is False
    assert res1.supports_dry_run is True
    assert res1.is_dry_run is False
    assert res1.suggested_action == "review_summary"
    assert res1.target_entity == "/workspace/config.json"
    assert "target_file" in res1.param_summary

    # Write with dry_run=True
    res2 = evaluator.evaluate(
        "write_to_file",
        {
            "target_file": "/workspace/config.json",
            "dry_run": True,
        },
    )
    assert res2.tier == "WRITE"
    assert res2.is_dry_run is True
    assert res2.suggested_action == "dry_run_simulated"


def test_level_3_high_risk_operations_need_confirmation_brake() -> None:
    evaluator = TieredRiskEvaluator()

    # High-risk tool name: delete_database
    res1 = evaluator.evaluate("delete_database", {"name": "production_db"})
    assert res1.tier == "HIGH_RISK"
    assert res1.need_confirmation is True
    assert res1.suggested_action == "NEED_CONFIRMATION"
    assert res1.confirmation_token is not None
    assert res1.confirmation_token.startswith("tok_")
    assert any("Irreversible mutation" in r for r in res1.risk_reasons)

    # High-risk tool name: remove_directory
    res2 = evaluator.evaluate("remove_directory", {"path": "/data/backups"})
    assert res2.tier == "HIGH_RISK"
    assert res2.need_confirmation is True

    # Dangerous shell command pattern: rm -rf
    res3 = evaluator.evaluate("run_shell", {"command": "rm -rf /var/log/app"})
    assert res3.tier == "HIGH_RISK"
    assert res3.need_confirmation is True
    assert any("rm" in r for r in res3.risk_reasons)

    # Dangerous shell command pattern: drop table
    res4 = evaluator.evaluate("execute_sql", {"command": "DROP TABLE critical_orders;"})
    assert res4.tier == "HIGH_RISK"
    assert res4.need_confirmation is True
    assert any("drop" in r.lower() for r in res4.risk_reasons)

    # Dangerous shell command pattern: kill -9
    res5 = evaluator.evaluate("bash_exec", {"CommandLine": "kill -9 8891"})
    assert res5.tier == "HIGH_RISK"
    assert res5.need_confirmation is True
