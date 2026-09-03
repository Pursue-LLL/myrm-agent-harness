"""Unit tests for Dual-Track Prior Audit Trail & Compliance Telemetry."""

from __future__ import annotations

import json

from myrm_agent_harness.observability.audit_trail import (
    ComplianceOutcome,
    ComplianceTrailExporter,
    DualTrackAuditCollector,
    PriorAuditState,
    compute_redaction_fingerprint,
    redact_string,
    sanitize_sensitive_data,
)


def test_zero_leakage_redaction_and_fingerprints():
    """Verify that credentials, API keys, passwords and tokens are scrubbed with length fingerprints."""
    raw_text = "Invoking external API with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 and sk-ant-api03-1234567890abcdef1234"
    scrubbed = redact_string(raw_text)

    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in scrubbed
    assert "sk-ant-api03-1234567890abcdef1234" not in scrubbed
    assert "[REDACTED:len=" in scrubbed
    assert ":fp=" in scrubbed

    nested_payload = {
        "user_id": "usr_9981",
        "api_key": "secret_live_key_998877",
        "nested": {
            "token": "ghp_1234567890abcdefghijklmnopqr",
            "safe_param": "/workspace/main.py",
        },
        "tags": ["env:prod", "auth_token_value_hidden"],
    }
    sanitized = sanitize_sensitive_data(nested_payload)
    assert sanitized["user_id"] == "usr_9981"
    assert "secret_live_key_998877" not in str(sanitized)
    assert sanitized["nested"]["safe_param"] == "/workspace/main.py"
    assert "[REDACTED:len=" in sanitized["nested"]["token"]

    fp = compute_redaction_fingerprint("sealed-content-body")
    assert fp.startswith("sha256:")
    assert len(fp) == 71  # sha256: + 64 hex chars


def test_dual_track_collector_lifecycle_and_pairing():
    """Test full fail-closed pre-act intent logging and post-act completion/refusal pairing."""
    collector = DualTrackAuditCollector(max_entries=100)

    # 1. Pre-act log intent for a permitted tool call
    intent_1 = collector.log_intent(
        session_id="sess_001",
        agent_id="code_assistant",
        tool_name="bash",
        intent_summary="Run tests in sandbox directory",
        proposed_args={"cmd": "pytest tests/test_core.py", "token": "secret_token_123"},
        rule_name="SANDBOX_COMMAND_EXECUTION",
        is_human_take_the_wheel=False,
    )
    assert intent_1.state == PriorAuditState.INTENT_LOGGED
    assert intent_1.outcome == ComplianceOutcome.PERMITTED
    assert "secret_token_123" not in str(intent_1.raw_intent_args)

    # 2. Complete post-act
    completed_1 = collector.complete_act(
        intent_1.entry_id,
        latency_ms=145.2,
        output_length=512,
        outcome=ComplianceOutcome.PERMITTED,
    )
    assert completed_1 is not None
    assert completed_1.state == PriorAuditState.COMPLETED
    assert completed_1.outcome == ComplianceOutcome.PERMITTED
    assert completed_1.latency_ms == 145.2
    assert completed_1.output_length == 512
    assert completed_1.completed_at is not None

    # 3. Log intent and refuse by security policy
    intent_2 = collector.log_intent(
        session_id="sess_001",
        agent_id="code_assistant",
        tool_name="fs_write",
        intent_summary="Write forbidden system file /etc/hosts",
        proposed_args={"path": "/etc/hosts"},
        rule_name="PROTECTED_SYSTEM_PATH_RESTRICTION",
        is_human_take_the_wheel=False,
    )
    refused_2 = collector.refuse_act(
        intent_2.entry_id,
        reason="Writing to /etc/hosts violates boundary sandbox policy.",
    )
    assert refused_2 is not None
    assert refused_2.state == PriorAuditState.REFUSED
    assert refused_2.outcome == ComplianceOutcome.REFUSED
    assert "violates boundary sandbox policy" in (refused_2.error_message or "")

    # 4. Log intent during human Take-The-Wheel
    intent_3 = collector.log_intent(
        session_id="sess_001",
        agent_id="code_assistant",
        tool_name="database_query",
        intent_summary="Manual emergency database migration under human supervision",
        proposed_args={"query": "ALTER TABLE users ADD COLUMN is_verified INT"},
        rule_name="HUMAN_SUPERVISION_GATE",
        is_human_take_the_wheel=True,
    )
    completed_3 = collector.complete_act(
        intent_3.entry_id,
        latency_ms=88.0,
        output_length=24,
        outcome=ComplianceOutcome.PERMITTED,
    )
    assert completed_3 is not None
    assert completed_3.is_human_take_the_wheel is True

    # 5. List entries and test filtering
    all_entries = collector.list_entries(session_id="sess_001")
    assert len(all_entries) == 3

    refused_entries = collector.list_entries(session_id="sess_001", outcome=ComplianceOutcome.REFUSED)
    assert len(refused_entries) == 1
    assert refused_entries[0].tool_name == "fs_write"


def test_audit_summary_stats_and_rule_telemetry():
    """Verify aggregated compliance rates, rule trigger distributions, and latency calculations."""
    collector = DualTrackAuditCollector()

    for i in range(10):
        intent = collector.log_intent(
            session_id="sess_bench",
            agent_id="agent_alpha",
            tool_name="fetch_url",
            intent_summary=f"Fetch domain resource {i}",
            rule_name="DOMAIN_ALLOWLIST_GATE",
        )
        if i < 7:
            collector.complete_act(intent.entry_id, latency_ms=50.0 + i, outcome=ComplianceOutcome.PERMITTED)
        else:
            collector.refuse_act(intent.entry_id, reason="Untrusted external domain")

    stats = collector.get_summary_stats(session_id="sess_bench")
    assert stats.total_entries == 10
    assert stats.permitted_count == 7
    assert stats.refused_count == 3
    assert stats.failed_count == 0
    assert stats.compliance_rate == 0.70
    assert stats.avg_latency_ms > 50.0

    assert len(stats.top_rules_triggered) == 1
    rule_hit = stats.top_rules_triggered[0]
    assert rule_hit.rule_name == "DOMAIN_ALLOWLIST_GATE"
    assert rule_hit.trigger_count == 10
    assert rule_hit.refused_count == 3
    assert rule_hit.refusal_rate == 0.30


def test_compliance_trail_export_formats():
    """Verify JSON, CSV, and Markdown export outputs for enterprise compliance audits."""
    collector = DualTrackAuditCollector()

    intent = collector.log_intent(
        session_id="sess_export",
        agent_id="compliance_bot",
        tool_name="git_commit",
        intent_summary="Commit audited code patch",
        proposed_args={"msg": "fix: security patch with token secret_abc123"},
        rule_name="GIT_INTEGRITY_POLICY",
        is_human_take_the_wheel=True,
    )
    collector.complete_act(intent.entry_id, latency_ms=120.0, output_length=100)

    report = ComplianceTrailExporter.generate_report(collector, session_id="sess_export", time_window_hours=24)
    assert report.summary.total_entries == 1
    assert report.summary.human_take_the_wheel_count == 1
    assert report.export_redaction_fingerprint.startswith("sha256:")

    # 1. JSON Export
    json_out = ComplianceTrailExporter.export_json(report)
    parsed_json = json.loads(json_out)
    assert parsed_json["report_id"] == report.report_id
    assert parsed_json["summary"]["compliance_rate"] == 1.0
    assert "secret_abc123" not in json_out

    # 2. CSV Export
    csv_out = ComplianceTrailExporter.export_csv(report)
    assert "entry_id,created_at,session_id,agent_id,tool_name" in csv_out
    assert "git_commit" in csv_out
    assert "YES" in csv_out  # is_human_take_the_wheel

    # 3. Markdown Export
    md_out = ComplianceTrailExporter.export_markdown(report)
    assert "# Enterprise Compliance & Audit Trail Dossier" in md_out
    assert "TakeWheel" in md_out
    assert "GIT_INTEGRITY_POLICY" in md_out
