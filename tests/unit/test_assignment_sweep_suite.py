"""
[POS] tests/unit/test_assignment_sweep_suite.py
[INPUT] myrm_agent_harness.core.security.assignment_sweep
[OUTPUT] Unit tests for QuotedKeySecretAssignmentSweepSuite
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.assignment_sweep import (
    AssignmentFormat,
    AssignmentKeyFamily,
    AssignmentSweepVerdict,
    QuotedKeySecretAssignmentSweepFacade,
)


@pytest.fixture
def facade() -> QuotedKeySecretAssignmentSweepFacade:
    return QuotedKeySecretAssignmentSweepFacade()


def test_quoted_json_and_single_quotes(facade: QuotedKeySecretAssignmentSweepFacade) -> None:
    content = """
    {
        "api_key": "sk-secret-token-abcdef123456",
        'client_secret': 'super-oauth-secret-998877',
        "database_port": 5432
    }
    """
    report = facade.sweep_text(content)

    assert report.verdict == AssignmentSweepVerdict.SUSPECTED_LEAK
    assert report.active_leaks_count == 2

    key_names = [f.key_name for f in report.findings]
    assert "api_key" in key_names
    assert "client_secret" in key_names

    for f in report.findings:
        assert f.format_kind in {AssignmentFormat.QUOTED_JSON, AssignmentFormat.COLON_ASSIGNMENT}
        assert f.is_exempt is False


def test_env_bracket_and_equals_assignments(facade: QuotedKeySecretAssignmentSweepFacade) -> None:
    content = """
    os.environ["API_KEY"] = "prod-secret-value-332211"
    config['app_secret'] = "app-sec-key-009988"
    export MY_API_KEY="env-key-secret-445566"
    """
    report = facade.sweep_text(content)

    assert report.verdict == AssignmentSweepVerdict.SUSPECTED_LEAK
    assert report.active_leaks_count == 3

    families = {f.key_family for f in report.findings}
    assert AssignmentKeyFamily.API_KEY in families
    assert AssignmentKeyFamily.SECRET in families


def test_alphanumeric_run_and_placeholders_stay_quiet(
    facade: QuotedKeySecretAssignmentSweepFacade,
) -> None:
    # Code with words that look like secrets but are benign continuous symbols or placeholders
    benign_code = """
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    token_count = len(tokens)
    secretive_behavior = False
    credentials_file = "/path/to/innocent/file"
    api_key = "your-api-key-here"
    password = "changeme"
    placeholder_val = "<INSERT_KEY_HERE>"
    """
    report = facade.sweep_text(benign_code)

    assert report.verdict == AssignmentSweepVerdict.CLEAN
    assert report.active_leaks_count == 0
    assert len(report.findings) == 0
    assert facade.is_clean(benign_code) is True


def test_loopback_database_url_exemption(facade: QuotedKeySecretAssignmentSweepFacade) -> None:
    # 1. Standard default dev credentials on localhost -> Exempted!
    local_dev_config = """
    DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/my_dev_db"
    """
    report = facade.sweep_text(local_dev_config)

    assert report.active_leaks_count == 0
    assert report.exempted_count == 1
    assert report.verdict == AssignmentSweepVerdict.EXEMPTED_LOCAL_DEV
    assert facade.is_clean(local_dev_config) is True

    exempt_finding = report.findings[0]
    assert exempt_finding.is_exempt is True
    assert "Exempted local development DSN" in (exempt_finding.exemption_reason or "")

    # 2. 127.0.0.1 with standard root/password -> Exempted!
    res_127 = facade.audit_database_url("mysql://root:root@127.0.0.1:3306/test")
    assert res_127 is not None
    assert res_127.is_exempt is True
    assert res_127.is_loopback is True


def test_non_loopback_database_url_strictly_flagged(
    facade: QuotedKeySecretAssignmentSweepFacade,
) -> None:
    # 1. Compose container service name (@db) with default postgres creds -> Must NOT be exempted!
    compose_dsn = "postgresql://postgres:postgres@db:5432/analytics"
    res_compose = facade.audit_database_url(compose_dsn)
    assert res_compose is not None
    assert res_compose.is_loopback is False
    assert res_compose.is_exempt is False
    assert "non-loopback host/service 'db'" in res_compose.audit_reason

    # 2. Remote production database url -> Must NOT be exempted!
    remote_dsn = "postgresql://app_user:s3cur3p@ss@db.prod.company.internal:5432/main"
    res_remote = facade.audit_database_url(remote_dsn)
    assert res_remote is not None
    assert res_remote.is_loopback is False
    assert res_remote.is_exempt is False

    # Full text sweep with remote DSN yields SUSPECTED_LEAK
    report = facade.sweep_text(f"DATABASE_URL='{remote_dsn}'")
    assert report.verdict == AssignmentSweepVerdict.SUSPECTED_LEAK
    assert report.active_leaks_count >= 1
    assert facade.is_clean(f"DATABASE_URL='{remote_dsn}'") is False
