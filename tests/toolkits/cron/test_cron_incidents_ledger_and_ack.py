"""Tests for durable cron incidents ledger, signature dedup, and ACK silencing.

Verifies:
- Stable signature generation across duration fluctuations.
- Sensitive credentials redaction in persisted errors.
- Three-state lifecycle transitions: detected -> alerted -> closed / resolved.
- Per-signature ACK silencing and suppression of repeat alerts.
- Job recovery auto-resolving and subsequent failure re-opening.
- False positive detection (exit 0 with missing or 0-byte output file).
- Failure classification logic.
- Cross-process / disk persistence across connection lifecycles.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.cron.incident_types import (
    CronIncident,
    dict_to_incident,
    incident_to_dict,
)
from myrm_agent_harness.toolkits.cron.incidents import (
    SqliteIncidentStore,
    calculate_error_signature,
    classify_failure_type,
    detect_false_positive,
    redact_sensitive_error,
)


def test_signature_dedup_and_duration_masking() -> None:
    job_id = "job-hourly-sync-12345"
    err1 = "Connection pool timed out: idle for 603s before drop"
    err2 = "Connection pool timed out: idle for 12.5 seconds before drop"
    err3 = "Connection pool timed out: idle for 42ms before drop"

    sig1 = calculate_error_signature(job_id, err1)
    sig2 = calculate_error_signature(job_id, err2)
    sig3 = calculate_error_signature(job_id, err3)

    assert sig1 == sig2 == sig3
    assert len(sig1) == 12

    # Different job or distinct error creates different signature
    diff_job_sig = calculate_error_signature("other-job-99", err1)
    diff_err_sig = calculate_error_signature(job_id, "HTTP 401 Unauthorized token expired")
    assert diff_job_sig != sig1
    assert diff_err_sig != sig1


def test_redact_sensitive_error() -> None:
    raw = "Request failed: Authorization: Bearer eyJhbGciOi.secret.token with key sk-abcdef123456789012345"
    scrubbed = redact_sensitive_error(raw)
    assert "Bearer" not in scrubbed
    assert "sk-abcdef" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_classify_failure_type() -> None:
    assert classify_failure_type("HTTP 429 Too Many Requests: quota exceeded") == "rate_limit"
    assert classify_failure_type("Network timeout after 30s") == "timeout"
    assert classify_failure_type("401 Unauthorized access") == "auth"
    assert classify_failure_type("SMTP delivery failed for recipient") == "delivery"
    assert classify_failure_type("Invalid configuration: missing key") == "config"
    assert classify_failure_type("Script returned non-zero exit code") == "script"
    assert classify_failure_type("Inference provider hallucination / error") == "agent"
    assert classify_failure_type("Something bizarre happened") == "unknown"


def test_false_positive_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        missing_file = str(tmp_path / "non_existent_report.csv")
        empty_file = str(tmp_path / "empty_report.csv")
        valid_file = str(tmp_path / "valid_report.csv")

        # Create empty file
        Path(empty_file).touch()
        # Create non-empty file
        Path(valid_file).write_text("col1,col2\nval1,val2\n", encoding="utf-8")

        # Exit code non-zero is not a false positive (it's already an explicit failure)
        fp_non_zero, _ = detect_false_positive(1, missing_file)
        assert not fp_non_zero

        # Exit 0 with missing file
        fp_missing, reason_missing = detect_false_positive(0, missing_file)
        assert fp_missing
        assert reason_missing is not None
        assert "does not exist" in reason_missing

        # Exit 0 with empty file
        fp_empty, reason_empty = detect_false_positive(0, empty_file)
        assert fp_empty
        assert reason_empty is not None
        assert "empty (0 bytes)" in reason_empty

        # Exit 0 with valid content
        fp_valid, reason_valid = detect_false_positive(0, valid_file)
        assert not fp_valid
        assert reason_valid is None


def test_incident_dict_roundtrip() -> None:
    now = datetime.now(UTC)
    incident = CronIncident(
        id="job123_abc123def456",
        job_id="job123",
        error_sig="abc123def456",
        state="detected",
        failure_type="rate_limit",
        first_seen_at=now,
        last_seen_at=now,
        error="Rate limit exceeded",
        output_file="/tmp/test.csv",
        alerted_at=None,
        acked_at=None,
        closed_at=None,
    )

    data = incident_to_dict(incident)
    restored = dict_to_incident(data)
    assert restored.id == incident.id
    assert restored.state == incident.state
    assert restored.failure_type == incident.failure_type
    assert restored.error == incident.error
    assert restored.output_file == incident.output_file


@pytest.mark.asyncio
async def test_incident_lifecycle_ack_and_silencing() -> None:
    store = SqliteIncidentStore(":memory:")
    job_id = "job-crawler-001"
    err = "upstream server 504 Gateway Timeout after 30s"

    # 1. First failure -> mints incident in 'detected' state
    inc1, is_new = await store.upsert_incident(job_id, err)
    assert is_new
    assert inc1.state == "detected"
    assert inc1.job_id == job_id
    assert inc1.failure_type == "timeout"
    assert inc1.alerted_at is None

    # 2. Operator / alert dispatcher alerts the failure
    ok_alert = await store.set_incident_state(inc1.id, "alerted")
    assert ok_alert
    alerted_inc = await store.get_incident(inc1.id)
    assert alerted_inc is not None
    assert alerted_inc.state == "alerted"
    assert alerted_inc.alerted_at is not None

    # 3. Same failure repeats next run -> refreshes last_seen_at, keeps 'alerted', is_new=False
    inc_repeat, is_new_repeat = await store.upsert_incident(
        job_id, "upstream server 504 Gateway Timeout after 45s"
    )
    assert not is_new_repeat
    assert inc_repeat.id == inc1.id
    assert inc_repeat.state == "alerted"

    # 4. Operator ACKs the incident -> transitions to 'closed'
    ok_ack = await store.ack_incident(inc1.id)
    assert ok_ack
    closed_inc = await store.get_incident(inc1.id)
    assert closed_inc is not None
    assert closed_inc.state == "closed"
    assert closed_inc.acked_at is not None
    assert closed_inc.closed_at is not None

    # 5. Subsequent run with identical error -> stays 'closed', silenced!
    inc_silenced, is_new_silenced = await store.upsert_incident(
        job_id, "upstream server 504 Gateway Timeout after 59s"
    )
    assert not is_new_silenced
    assert inc_silenced.state == "closed"

    # 6. Changed error mints a brand new incident!
    new_err = "fatal: sqlite disk I/O error"
    inc_new_err, is_new_err = await store.upsert_incident(job_id, new_err)
    assert is_new_err
    assert inc_new_err.id != inc1.id
    assert inc_new_err.state == "detected"


@pytest.mark.asyncio
async def test_job_recovery_and_reopen_on_recurrence() -> None:
    store = SqliteIncidentStore(":memory:")
    job_id = "job-nightly-backup"
    err = "Auth failed: 403 Forbidden"

    # Initial incident detected
    inc, is_new = await store.upsert_incident(job_id, err)
    assert is_new
    assert inc.state == "detected"

    # Job successfully runs on next tick -> mark resolved
    resolved_count = await store.close_incidents_for_recovered_job(job_id)
    assert resolved_count == 1

    resolved_inc = await store.get_incident(inc.id)
    assert resolved_inc is not None
    assert resolved_inc.state == "resolved"

    # Closed incidents are operator-silenced and shouldn't be affected by auto-resolve
    inc_other, _ = await store.upsert_incident("job-other", "Rate limit 429")
    await store.ack_incident(inc_other.id)
    await store.close_incidents_for_recovered_job("job-other")
    closed_check = await store.get_incident(inc_other.id)
    assert closed_check is not None
    assert closed_check.state == "closed"

    # When the resolved error recurs in the future -> re-opens as 'detected'!
    reopened_inc, is_reopened = await store.upsert_incident(job_id, err)
    assert is_reopened
    assert reopened_inc.id == inc.id
    assert reopened_inc.state == "detected"
    assert reopened_inc.alerted_at is None
    assert reopened_inc.closed_at is None


@pytest.mark.asyncio
async def test_query_filter_and_counts() -> None:
    store = SqliteIncidentStore(":memory:")
    await store.upsert_incident("job-a", "timeout error")
    inc_b, _ = await store.upsert_incident("job-b", "429 rate limit")
    await store.ack_incident(inc_b.id)

    # Count total and filtered
    assert await store.count_incidents() == 2
    assert await store.count_incidents(state="detected") == 1
    assert await store.count_incidents(state="closed") == 1
    assert await store.count_incidents(job_id="job-a") == 1

    # List queries
    open_list = await store.list_incidents(state="detected")
    assert len(open_list) == 1
    assert open_list[0].job_id == "job-a"

    closed_list = await store.list_incidents(state="closed")
    assert len(closed_list) == 1
    assert closed_list[0].job_id == "job-b"


@pytest.mark.asyncio
async def test_disk_persistence_across_instances() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "cron_incidents.db"

        # Instance 1 writes and acks incident
        store1 = SqliteIncidentStore(db_file)
        inc, is_new = await store1.upsert_incident(
            "job-persistent", "script exited with code 127", output_file="/app/out.json"
        )
        assert is_new
        await store1.ack_incident(inc.id)

        # Instance 2 connects to same database
        store2 = SqliteIncidentStore(db_file)
        loaded = await store2.get_incident(inc.id)
        assert loaded is not None
        assert loaded.id == inc.id
        assert loaded.state == "closed"
        assert loaded.failure_type == "script"
        assert loaded.output_file == "/app/out.json"
