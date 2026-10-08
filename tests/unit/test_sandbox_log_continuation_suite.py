"""Unit tests for SandboxLogRedactor and ExecutionContinuationAuditEngine."""

from __future__ import annotations

from myrm_agent_harness.core.security.sandbox_log_continuation import (
    ContinuationStatus,
    ExecutionContinuationAuditEngine,
    HeartbeatSignal,
    RedactionCategory,
    SandboxLogRedactor,
)


def test_redactor_masks_api_keys_and_tokens() -> None:
    redactor = SandboxLogRedactor()
    raw_log = (
        "Connecting with sk-1234567890abcdef12345678 and token ghp_ABCDEF1234567890XYZW "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.do_not_leak_signature"
    )
    result = redactor.redact_text(raw_log)

    assert "[REDACTED_API_KEY]" in result.redacted_text
    assert (
        "[REDACTED_JWT_TOKEN]" in result.redacted_text
        or "Bearer [REDACTED_BEARER_TOKEN]" in result.redacted_text
    )
    assert "sk-1234567890abcdef12345678" not in result.redacted_text
    assert "ghp_ABCDEF1234567890XYZW" not in result.redacted_text
    assert RedactionCategory.API_KEY in result.categories_redacted
    assert RedactionCategory.BEARER_TOKEN in result.categories_redacted


def test_redactor_masks_private_keys_and_urls() -> None:
    redactor = SandboxLogRedactor()
    raw_pem = """
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Y3t8LgN...
...some secret private key data...
-----END RSA PRIVATE KEY-----
"""
    result_pem = redactor.redact_text(raw_pem)
    assert "[REDACTED_PRIVATE_KEY]" in result_pem.redacted_text
    assert "MIIEowIBAAKCAQEA0Y3t8LgN" not in result_pem.redacted_text
    assert RedactionCategory.PRIVATE_KEY in result_pem.categories_redacted

    raw_url = "git clone https://git_user:my_secret_token_123@github.com/repo.git"
    result_url = redactor.redact_text(raw_url)
    assert (
        result_url.redacted_text
        == "git clone https://git_user:[REDACTED_CREDENTIAL]@github.com/repo.git"
    )
    assert RedactionCategory.URL_CREDENTIAL in result_url.categories_redacted


def test_redactor_masks_env_and_commands() -> None:
    redactor = SandboxLogRedactor()
    cmd = "export API_KEY=secret_key_value_999 && python run.py"
    args = ["--password=super_secret_passwd", "--verbose", "db_host=prod.internal"]

    redacted_cmd, redacted_args = redactor.redact_command(cmd, args)
    assert "export API_KEY=[REDACTED_SECRET] && python run.py" in redacted_cmd
    assert "--password=[REDACTED_SECRET]" in redacted_args[0]
    assert redacted_args[1] == "--verbose"
    assert redacted_args[2] == "db_host=prod.internal"


def test_continuation_audit_valid_flow() -> None:
    engine = ExecutionContinuationAuditEngine()
    engine.register_run(
        run_id="run-001",
        task_id="task-100",
        assignee_agent_id="agent-coder",
        is_terminal=False,
        started_at=1000.0,
    )

    # 1. New root run is valid
    root_verdict = engine.audit_continuation(
        task_id="task-100",
        requesting_agent_id="agent-coder",
        proposed_run_id="run-001",
        resume_source_run_id=None,
    )
    assert root_verdict.is_resumable is True
    assert root_verdict.status == ContinuationStatus.VALID

    # 2. Add heartbeat
    heartbeat_ok = engine.record_heartbeat(
        HeartbeatSignal(
            run_id="run-001",
            timestamp=1020.0,
            seq=1,
            status="running",
        )
    )
    assert heartbeat_ok is True

    # 3. Resume continuation with fresh heartbeat
    resume_verdict = engine.audit_continuation(
        task_id="task-100",
        requesting_agent_id="agent-coder",
        proposed_run_id="run-002",
        resume_source_run_id="run-001",
        current_time=1030.0,
        max_heartbeat_gap_seconds=60.0,
    )
    assert resume_verdict.is_resumable is True
    assert resume_verdict.status == ContinuationStatus.VALID
    assert resume_verdict.last_heartbeat_age_sec == 10.0


def test_continuation_audit_failure_scenarios() -> None:
    engine = ExecutionContinuationAuditEngine()
    engine.register_run(
        run_id="run-source",
        task_id="task-200",
        assignee_agent_id="agent-alpha",
        is_terminal=False,
        started_at=1000.0,
    )
    engine.record_heartbeat(
        HeartbeatSignal(
            run_id="run-source",
            timestamp=1005.0,
            seq=1,
            status="running",
        )
    )

    # A. Missing origin run
    verdict_missing = engine.audit_continuation(
        task_id="task-200",
        requesting_agent_id="agent-alpha",
        proposed_run_id="run-next",
        resume_source_run_id="nonexistent-run",
        current_time=1010.0,
    )
    assert verdict_missing.is_resumable is False
    assert verdict_missing.status == ContinuationStatus.MISSING_ORIGIN_RUN

    # B. Ownership mismatch
    verdict_owner = engine.audit_continuation(
        task_id="task-200",
        requesting_agent_id="agent-imposter",
        proposed_run_id="run-next",
        resume_source_run_id="run-source",
        current_time=1010.0,
    )
    assert verdict_owner.is_resumable is False
    assert verdict_owner.status == ContinuationStatus.OWNERSHIP_MISMATCH

    # C. Stale heartbeat (gap 70s > 60s limit)
    verdict_stale = engine.audit_continuation(
        task_id="task-200",
        requesting_agent_id="agent-alpha",
        proposed_run_id="run-next",
        resume_source_run_id="run-source",
        current_time=1076.0,
        max_heartbeat_gap_seconds=60.0,
    )
    assert verdict_stale.is_resumable is False
    assert verdict_stale.status == ContinuationStatus.STALE_HEARTBEAT
    assert verdict_stale.last_heartbeat_age_sec == 71.0

    # D. Terminated task
    engine.mark_run_terminal("run-source")
    verdict_term = engine.audit_continuation(
        task_id="task-200",
        requesting_agent_id="agent-alpha",
        proposed_run_id="run-next",
        resume_source_run_id="run-source",
        current_time=1010.0,
    )
    assert verdict_term.is_resumable is False
    assert verdict_term.status == ContinuationStatus.TASK_TERMINATED
